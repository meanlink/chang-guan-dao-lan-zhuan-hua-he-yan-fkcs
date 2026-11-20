"""导览试点双时间复盘引擎的标准库单测。

仅依赖 Python 标准库，运行：
    cd backend && python -m tests.test_replay
覆盖：确定性输入、当时/今天两次核验、补报累加、更正跨营业日挪动、
撤销、收讫边界、批次中断恢复等价、严格 JSON、参数与事件校验、
并发补报不侵入已圈定样本。
"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services import replay  # noqa: E402
from src.services.flow_seed import (  # noqa: E402
    seed_flow_events, BUSINESS_DAY, NEXT_DAY, THEN, NOW)


def ev(flow_no, zone, date, kind, visitors, received, note=''):
    return {'flow_no': flow_no, 'zone': zone, 'business_date': date,
            'event_type': kind, 'visitors': visitors, 'received_at': received,
            'note': note}


class SeedDeterminism(unittest.TestCase):
    def test_seed_is_deterministic(self):
        self.assertEqual(seed_flow_events(), seed_flow_events())

    def test_all_seed_events_valid(self):
        for e in seed_flow_events():
            replay.validate_event(e)


class AsOfConclusions(unittest.TestCase):
    def setUp(self):
        self.events = seed_flow_events()
        then_state = replay.replay(self.events, BUSINESS_DAY, '全部', THEN)
        now_state = replay.replay(self.events, BUSINESS_DAY, '全部', NOW)
        self.then = replay.summarize(then_state, BUSINESS_DAY, '全部', THEN)
        self.now = replay.summarize(now_state, BUSINESS_DAY, '全部', NOW)
        self.diff = replay.diff_conclusions(
            replay.active_rows(then_state, BUSINESS_DAY, '全部'),
            replay.active_rows(now_state, BUSINESS_DAY, '全部'),
            self.then, self.now,
            then_all=replay.all_records_map(then_state),
            now_all=replay.all_records_map(now_state))

    def test_then_only_sees_reports_received_by_cutoff(self):
        # 午间盘点前：F-1001(120) + F-1002(200) + F-1003(88)
        self.assertEqual(self.then['visitors'], 408)
        self.assertEqual(self.then['active_records'], 3)
        self.assertEqual(self.then['flow_numbers'], ['F-1001', 'F-1002', 'F-1003'])

    def test_now_includes_late_supplements_and_new_report(self):
        # F-1001=138, F-1002=235, F-1005=42；F-1003 被挪走、F-1004 被撤销
        self.assertEqual(self.now['visitors'], 415)
        self.assertEqual(self.now['active_records'], 3)
        self.assertEqual(self.now['flow_numbers'], ['F-1001', 'F-1002', 'F-1005'])

    def test_difference_locates_every_changed_record(self):
        self.assertEqual(self.diff['visitors_delta'], 7)
        by_no = {d['flow_no']: d for d in self.diff['details']}
        self.assertEqual(by_no['F-1001']['delta_visitors'], 18)
        self.assertEqual(by_no['F-1002']['delta_visitors'], 35)
        self.assertIsNone(by_no['F-1003']['now'])          # 挪到下一营业日
        self.assertIn('更正挪至另一营业日', by_no['F-1003']['reasons'])
        self.assertIsNone(by_no['F-1005']['then'])         # 迟到的新号
        self.assertEqual(self.diff['changed_records'], 4)

    def test_result_is_strict_json(self):
        payload = {'then': self.then, 'now': self.now, 'difference': self.diff}
        json.dumps(payload, allow_nan=False)  # 不允许 NaN/Inf


class EventSemantics(unittest.TestCase):
    def test_supplement_accumulates_same_flow_no(self):
        events = [ev('A', '星空厅', BUSINESS_DAY, 'report', 10, 1.0),
                  ev('A', '星空厅', BUSINESS_DAY, 'supplement', 5, 2.0)]
        s = replay.replay(events, BUSINESS_DAY, '全部', 10.0)
        self.assertEqual(replay.summarize(s, BUSINESS_DAY, '全部', 10.0)['visitors'], 15)

    def test_correction_moves_record_to_another_business_day(self):
        events = [ev('A', '机械坊', BUSINESS_DAY, 'report', 88, 1.0),
                  ev('A', '机械坊', NEXT_DAY, 'correction', 90, 2.0)]
        s = replay.replay(events, BUSINESS_DAY, '全部', 10.0)
        day1 = replay.summarize(s, BUSINESS_DAY, '全部', 10.0)
        day2 = replay.summarize(s, NEXT_DAY, '全部', 10.0)
        self.assertEqual(day1['active_records'], 0)
        self.assertEqual(day2['active_records'], 1)
        self.assertEqual(day2['visitors'], 90)

    def test_retract_removes_record(self):
        events = [ev('A', '机械坊', BUSINESS_DAY, 'report', 60, 1.0),
                  ev('A', '机械坊', BUSINESS_DAY, 'retract', 0, 2.0)]
        s = replay.replay(events, BUSINESS_DAY, '全部', 10.0)
        self.assertEqual(replay.summarize(s, BUSINESS_DAY, '全部', 10.0)['active_records'], 0)

    def test_diff_distinguishes_retract_from_cross_day_move(self):
        # A 被撤销（全量状态中消失）；B 被更正到下一营业日（全量状态仍在）。
        events = [
            ev('A', '机械坊', BUSINESS_DAY, 'report', 60, 1.0),
            ev('A', '机械坊', BUSINESS_DAY, 'retract', 0, 4.0),
            ev('B', '机械坊', BUSINESS_DAY, 'report', 70, 1.0),
            ev('B', '机械坊', NEXT_DAY, 'correction', 72, 4.0),
        ]
        then_state = replay.replay(events, BUSINESS_DAY, '全部', 2.0)
        now_state = replay.replay(events, BUSINESS_DAY, '全部', 10.0)
        diff = replay.diff_conclusions(
            replay.active_rows(then_state, BUSINESS_DAY, '全部'),
            replay.active_rows(now_state, BUSINESS_DAY, '全部'),
            replay.summarize(then_state, BUSINESS_DAY, '全部', 2.0),
            replay.summarize(now_state, BUSINESS_DAY, '全部', 10.0),
            then_all=replay.all_records_map(then_state),
            now_all=replay.all_records_map(now_state))
        reasons = {d['flow_no']: d['reasons'] for d in diff['details']}
        self.assertIn('记录被撤销', reasons['A'])
        self.assertIn('更正挪至另一营业日', reasons['B'])

    def test_cutoff_is_inclusive(self):
        events = [ev('A', '星空厅', BUSINESS_DAY, 'report', 10, 100.0)]
        inside = replay.summarize(replay.replay(events, BUSINESS_DAY, '全部', 100.0),
                                  BUSINESS_DAY, '全部', 100.0)
        outside = replay.summarize(replay.replay(events, BUSINESS_DAY, '全部', 99.999),
                                   BUSINESS_DAY, '全部', 99.999)
        self.assertEqual(inside['visitors'], 10)
        self.assertEqual(outside['visitors'], 0)

    def test_correction_moves_record_to_another_zone(self):
        events = [ev('A', '星空厅', BUSINESS_DAY, 'report', 10, 1.0),
                  ev('A', '水世界', BUSINESS_DAY, 'correction', 12, 2.0)]
        s = replay.replay(events, BUSINESS_DAY, '水世界', 10.0)
        water = replay.summarize(s, BUSINESS_DAY, '水世界', 10.0)
        star = replay.summarize(s, BUSINESS_DAY, '星空厅', 10.0)
        self.assertEqual(water['active_records'], 1)
        self.assertEqual(water['visitors'], 12)
        # 旧展区视图不应残留该记录（更正已整体挪走）。
        self.assertEqual(star['active_records'], 0)

    def test_zone_filter(self):
        events = [ev('A', '星空厅', BUSINESS_DAY, 'report', 10, 1.0),
                  ev('B', '水世界', BUSINESS_DAY, 'report', 20, 1.0)]
        s = replay.replay(events, BUSINESS_DAY, '水世界', 10.0)
        summary = replay.summarize(s, BUSINESS_DAY, '水世界', 10.0)
        self.assertEqual(summary['visitors'], 20)
        self.assertEqual(summary['by_zone'], [{'zone': '水世界', 'visitors': 20}])


class BatchedResume(unittest.TestCase):
    def test_batched_resume_equals_one_shot(self):
        events = seed_flow_events()
        ref_then = replay.summarize(replay.replay(events, BUSINESS_DAY, '全部', THEN),
                                    BUSINESS_DAY, '全部', THEN)
        ref_now = replay.summarize(replay.replay(events, BUSINESS_DAY, '全部', NOW),
                                   BUSINESS_DAY, '全部', NOW)
        # 极小批大小强制跨越多个批边界；每批后状态落库，模拟任意点崩溃后续算。
        then_state, now_state = replay._blank_state(), replay._blank_state()
        cursor, total, batch = 0, len(events), 3
        while cursor < total:
            end = min(cursor + batch, total)
            replay.replay(events, BUSINESS_DAY, '全部', THEN,
                          state=then_state, limit=end - then_state['processed'])
            replay.replay(events, BUSINESS_DAY, '全部', NOW,
                          state=now_state, limit=end - now_state['processed'])
            cursor = end
        self.assertEqual(
            replay.summarize(then_state, BUSINESS_DAY, '全部', THEN), ref_then)
        self.assertEqual(
            replay.summarize(now_state, BUSINESS_DAY, '全部', NOW), ref_now)
        self.assertEqual(then_state['processed'], total)

    def test_repeated_replay_does_not_double_count(self):
        events = seed_flow_events()
        s = replay._blank_state()
        for _ in range(3):
            replay.replay(events, BUSINESS_DAY, '全部', NOW, state=s)
        # 已消费的事件不会因重试再次入账。
        self.assertEqual(s['processed'], len(events))
        self.assertEqual(
            replay.summarize(s, BUSINESS_DAY, '全部', NOW)['visitors'], 415)


class FrozenSample(unittest.TestCase):
    def test_concurrent_late_event_kept_out_of_frozen_sample(self):
        events = seed_flow_events()
        # 创建复盘时按收讫范围圈定样本（仅 id 顺序），等价 service 层 _frozen_sample。
        frozen_ids = [i for i, e in enumerate(events) if e['received_at'] <= NOW]
        # 取样之后到达的并发补报：不得进入本次复盘。
        late = ev('F-9999', '星空厅', BUSINESS_DAY, 'supplement', 777, NOW + 1000)
        all_events = events + [late]
        sample = [all_events[i] for i in frozen_ids]
        s = replay.replay(sample, BUSINESS_DAY, '全部', NOW)
        summary = replay.summarize(s, BUSINESS_DAY, '全部', NOW)
        self.assertEqual(summary['visitors'], 415)  # 与无并发补报时一致
        self.assertNotIn('F-9999', summary['flow_numbers'])


class Validation(unittest.TestCase):
    def _base(self):
        return ev('A', '星空厅', BUSINESS_DAY, 'report', 10, 1.0)

    def test_missing_field_rejected(self):
        e = self._base(); del e['flow_no']
        with self.assertRaises(ValueError):
            replay.validate_event(e)

    def test_unknown_event_type_rejected(self):
        e = self._base(); e['event_type'] = 'hack'
        with self.assertRaises(ValueError):
            replay.validate_event(e)

    def test_negative_and_non_integer_visitors_rejected(self):
        for bad in (-1, 1.5):
            e = self._base(); e['visitors'] = bad
            with self.assertRaises(ValueError):
                replay.validate_event(e)

    def test_non_finite_received_at_rejected(self):
        e = self._base(); e['received_at'] = math.nan
        with self.assertRaises(ValueError):
            replay.validate_event(e)

    def test_bad_business_date_rejected(self):
        e = self._base(); e['business_date'] = '11-06'
        with self.assertRaises(ValueError):
            replay.validate_event(e)


if __name__ == '__main__':
    unittest.main(verbosity=2)
