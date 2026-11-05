import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_knowledge_base as u


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.song = {'title': 'Test', 'artist': 'Artist', 'category': '舞萌',
                     'version': '舞萌DX 2026', 'lev_bas': '4'}
        self.detail = {'source': 'divingfish', 'songId': '1', 'songTitle': 'Test',
                       'artist': 'Artist', 'sheetType': 'std', 'difficulty': 'basic',
                       'level': '4', 'internalLevelValue': 4.0, 'notes': {'tap': 10},
                       'noteDesigner': '-'}

    def build(self, details=None, aliases=None):
        details = [self.detail] if details is None else details
        def fetch(url, timeout):
            if url == u.CN_MAIDATA_URL:
                return [self.song]
            if url == u.ALIAS_URL:
                if aliases is None:
                    raise RuntimeError('alias offline')
                return aliases
            if url == u.DIVING_FISH_MUSIC_URL:
                return [{}]
            raise AssertionError(url)
        with patch.object(u, 'fetch_json', side_effect=fetch), \
             patch.object(u, 'detail_rows_from_divingfish', return_value=details), \
             patch.object(u, 'fetch_text', return_value=''), \
             patch.object(u, 'load_annotations', return_value={}), \
             patch.object(u, 'load_old_rows', return_value=[{
                 'title': 'Test', 'artist': 'Artist', 'type': 'standard',
                 'difficulty': 'basic', 'aliases': ['Old alias'], 'chart_tags': ['交互'],
                 'ds': 4.0, 'id': 1} ]):
            return u.build_snapshot(1)

    def test_alias_failure_keeps_alias_and_chart_tags(self):
        songs, rows = self.build()
        self.assertIn('Old alias', songs[0]['aliases'])
        self.assertEqual(rows[0]['chart_tags'], ['交互'])
        u.validate_snapshot(songs, rows)

    def test_new_alias_merges_instead_of_replacing(self):
        songs, _ = self.build(aliases={'code': 0, 'content': [{'SongID': 1, 'Alias': ['New alias']}]})
        self.assertTrue({'Old alias', 'New alias'} <= set(songs[0]['aliases']))

    def test_conflicting_detail_does_not_restore_stale_ds(self):
        detail = dict(self.detail, internalLevelValue=5.0)
        _, rows = self.build([detail])
        self.assertIsNone(rows[0]['ds'])

    def test_wrong_artist_is_not_matched(self):
        detail = dict(self.detail, artist='Other artist')
        self.assertIsNone(u.choose_group(self.song, 'std', {'Test': [detail]}, [detail]))

    def test_tied_candidates_are_unresolved(self):
        other = dict(self.detail, songId='2')
        self.assertIsNone(u.choose_group(self.song, 'std', {'Test': [self.detail, other]}, []))

    def test_empty_cn_refuses_write(self):
        with patch.object(u, 'fetch_json', return_value=[]):
            with self.assertRaises(ValueError):
                u.build_snapshot(1)

    def test_rejects_missing_duplicate_chart_and_bad_ds(self):
        songs, rows = self.build()
        for invalid in ([], rows + rows, [dict(rows[0], ds=6.0)], [dict(rows[0], id=2)]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    u.validate_snapshot(songs, invalid)

    def test_committed_snapshot_and_link_disambiguation(self):
        songs = json.loads(u.SONGS_FILE.read_text())
        rows = u.load_old_rows()
        u.validate_snapshot(songs, rows)
        meta = json.loads(u.SNAPSHOT_META.read_text(encoding="utf-8"))
        self.assertEqual((len(songs), len(rows)), (meta["songs"], meta["charts"]))
        self.assertEqual(meta["charts_with_ds"], sum(1 for r in rows if r["ds"] is not None))
        self.assertGreaterEqual(len(songs), 1200)
        self.assertGreaterEqual(len(rows), 5000)
        self.assertEqual({s['std_id'] for s in songs if s['title'] == 'Link'}, {131, 383})
        self.assertTrue(all(r['id'] is not None for r in rows))
        constants = {(r['type'], r['id'], r['difficulty']): r['ds'] for r in rows}
        mismatched = [(s['title'], typ, diff) for s in songs
                      for typ, sid in (('standard', s['std_id']), ('dx', s['dx_id']))
                      for diff in u.DIFFICULTIES
                      if s['ds'][typ][diff] != constants.get((typ, sid, diff))]
        self.assertEqual(mismatched, [])

    def test_ds_threshold_and_nonfinite_values(self):
        self.assertEqual(u.ds_label(12.5), '12')
        self.assertEqual(u.ds_label(12.6), '12+')
        # 1-6 级没有 “+” 档，定数 6.9 仍是 6
        self.assertEqual(u.ds_label(6.9), '6')
        for value in (None, 'bad', float('nan'), float('inf'), 0):
            self.assertIsNone(u.ds_label(value))


class OnecatTests(unittest.TestCase):
    payload = [
        {'id': '11037', 'type': 'DX', 'title': '[X]', 'basic_info': {'genre': '流行&动漫'},
         'level': ['3', '6', '9', '12'], 'ds': [3.0, 6.0, 9.4, 12.0]},
        {'id': '100772', 'type': 'SD', 'title': '[狂]FREEDOM DiVE', 'basic_info': {'genre': '宴会場'},
         'level': ['15?'], 'ds': [15.0]},
        {'id': '363', 'type': 'SD', 'title': 'Oshama Scramble!', 'basic_info': {'genre': '舞萌'},
         'level': ['6', '8+', '11+', '14'], 'ds': [6.0, 8.6, 11.9, 14.5]},
    ]

    def rows_and_songs(self):
        rows = [
            {'id': 11037, 'title': '[X]', 'artist': 'A', 'type': 'dx', 'difficulty': 'basic',
             'value': '4', 'ds': None, 'ds_source': None},
            {'id': 363, 'title': 'Oshama Scramble!', 'artist': 'B', 'type': 'standard',
             'difficulty': 'master', 'value': '14', 'ds': 14.0, 'ds_source': 'divingfish'},
        ]
        songs = [{'title': '[X]', 'artist': 'A', 'version': '舞萌DX', 'std_id': None, 'dx_id': 11037,
                  'difficulty': {'standard': {}, 'dx': {'basic': '4', 'advanced': None,
                                                        'expert': None, 'master': None, 'remaster': None}}}]
        return songs, rows

    def test_utage_excluded_but_bracket_titles_kept(self):
        index = u.onecat_index(self.payload)
        self.assertIn(('dx', 11037), index)
        self.assertNotIn(('standard', 100772), index)

    def test_apply_sets_ds_and_resyncs_song_level(self):
        songs, rows = self.rows_and_songs()
        _, rows, stats = u.apply_onecat(songs, rows, self.payload)
        self.assertEqual((rows[0]['ds'], rows[0]['value'], rows[0]['ds_source']), (3.0, '3', 'onecat'))
        self.assertEqual(songs[0]['difficulty']['dx']['basic'], '3')
        self.assertEqual(stats['补全定数'], 1)
        # 旧定数 14.0 与新源 14.5 冲突时按新源修正，显示等级仍是 14
        self.assertEqual(stats['修正定数'], 1)
        self.assertEqual((rows[1]['ds'], rows[1]['value']), (14.5, '14'))

    def test_unknown_song_keeps_snapshot_values(self):
        songs, rows = self.rows_and_songs()
        rows.append({'id': 99999, 'title': 'Gone', 'artist': 'C', 'type': 'dx',
                     'difficulty': 'basic', 'value': '5', 'ds': None, 'ds_source': None})
        _, rows, stats = u.apply_onecat(songs, rows, self.payload)
        self.assertEqual((rows[-1]['ds'], rows[-1]['value'], rows[-1]['ds_source']), (None, '5', None))
        self.assertEqual(stats['源未收录'], 1)

    def test_add_missing_charts_fills_gap(self):
        songs, rows = self.rows_and_songs()
        added = u.add_missing_charts(songs, rows, self.payload)
        self.assertEqual([(r['id'], r['difficulty'], r['value']) for r in added],
                         [(11037, 'advanced', '6'), (11037, 'expert', '9'), (11037, 'master', '12')])
        self.assertEqual(songs[0]['difficulty']['dx']['master'], '12')
        self.assertEqual(songs[0]['ds']['dx']['expert'], 9.4)

    def test_offline_render_is_repeatable(self):
        songs = json.loads(u.SONGS_FILE.read_text())
        rows = u.load_old_rows()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(u, 'SONGS_FILE', root / 'songs.json'), \
                 patch.object(u, 'LEVEL_INDEX', root / 'level_index.json'), \
                 patch.object(u, 'SNAPSHOT_META', root / 'snapshot_meta.json'), \
                 patch.object(u, 'KB_DIR', root / 'knowledge_base'):
                u.write_snapshot(songs, rows)
                first = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                u.write_snapshot(songs, rows)
                second = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
