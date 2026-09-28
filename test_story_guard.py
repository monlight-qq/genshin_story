"""不发送真实键鼠输入的回归测试：python -m unittest discover -s genshin_story"""

import contextlib
import ctypes
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_story as app
from story_guard import Marker, FixedPoint, PATCH_SIZE, StoryGuard, load_markers, save_markers, load_option, save_option
from story_guard import CloseGuard, load_close_markers, save_close_marker


def icon(background=40, foreground=240):
    pixels = bytearray()
    for y in range(PATCH_SIZE):
        for x in range(PATCH_SIZE):
            value = foreground if (8 <= x <= 11 and 4 <= y <= 20) or (8 <= x <= 20 and 17 <= y <= 20) else background
            pixels.extend((value, value, value, 0))
    return bytes(pixels)


def close_icon():
    pixels = bytearray()
    for y in range(PATCH_SIZE):
        for x in range(PATCH_SIZE):
            stroke = 4 <= x <= 20 and 4 <= y <= 20 and (abs(x - y) <= 1 or abs(x + y - 24) <= 1)
            value = 240 if stroke else 40
            pixels.extend((value, value, value, 0))
    return bytes(pixels)


def marker():
    return Marker.calibrate(1920, 1080, 100, 100, icon())


class MarkerTests(unittest.TestCase):
    def test_close_templates_persist_and_same_position_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'close.json'
            self.assertEqual(load_close_markers(path), [])
            first = marker()
            markers = save_close_marker(path, [], first)
            replacement = marker()
            replacement.x += 3
            markers = save_close_marker(path, markers, replacement)
            self.assertEqual(len(markers), 1)
            other = marker()
            other.x += 100
            markers = save_close_marker(path, markers, other)
            self.assertEqual(load_close_markers(path), markers)
            self.assertEqual(len(markers), 2)
    def test_fixed_option_point_persists_without_image_edges(self):
        point = FixedPoint(2560, 1600, 1800, 950)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'option.json'
            save_option(path, point)
            self.assertEqual(load_option(path), point)
        with self.assertRaises(ValueError):
            FixedPoint.from_dict({'width': 2560, 'height': 1600, 'x': 2560, 'y': 950})
    def test_old_saved_marker_format_still_loads(self):
        data = marker().as_dict()
        del data['neutral']
        self.assertTrue(Marker.from_dict(data).neutral)

    def test_shifted_icon_matches_and_two_choices_are_sorted_top_first(self):
        width, height = 57, 180
        image = bytearray(bytes((40, 40, 40, 0)) * width * height)
        sample = icon()
        for x, y in ((14, 90), (18, 30)):
            for row in range(PATCH_SIZE):
                offset = ((y + row) * width + x) * 4
                image[offset:offset + PATCH_SIZE * 4] = sample[row * PATCH_SIZE * 4:(row + 1) * PATCH_SIZE * 4]
        hits = marker().scan(bytes(image), width, height, 0.9)
        self.assertEqual([(x, y) for x, y, _ in hits], [(18, 30), (14, 90)])
        small = bytearray(bytes((40, 40, 40, 0)) * 29 * 29)
        for row in range(PATCH_SIZE):
            offset = ((row + 3) * 29 + 1) * 4
            small[offset:offset + PATCH_SIZE * 4] = sample[row * PATCH_SIZE * 4:(row + 1) * PATCH_SIZE * 4]
        self.assertEqual(marker().best_score(bytes(small), 29, 29), 1)

    def test_search_rejects_uniform_background(self):
        pixels = bytes((240, 240, 240, 0)) * 57 * 100
        self.assertEqual(marker().scan(pixels, 57, 100, 0.9), [])

    def test_colored_option_icon_and_option_persistence(self):
        pixels = bytearray(icon())
        for i in range(0, len(pixels), 4):
            if pixels[i] == 240:
                pixels[i:i + 3] = bytes((40, 200, 240))
        template = Marker.calibrate(1920, 1080, 100, 100, bytes(pixels), neutral=False)
        self.assertEqual(template.score(bytes(pixels)), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'option.json'
            self.assertIsNone(load_option(path))
            save_option(path, template)
            restored = load_option(path)
            self.assertFalse(restored.neutral)
            self.assertEqual(restored.score(bytes(pixels)), 1)

    def test_background_and_brightness_changes(self):
        template = marker()
        self.assertEqual(template.score(icon()), 1)
        self.assertEqual(template.score(icon(background=120, foreground=210)), 1)
        self.assertEqual(template.score(icon(background=0, foreground=0)), 0)
        self.assertEqual(template.score(icon(background=240, foreground=240)), 0)

    def test_blank_calibration_rejected(self):
        with self.assertRaises(ValueError):
            Marker.calibrate(1920, 1080, 100, 100, icon(240, 240))

    def test_wrong_shape_rejected(self):
        with self.assertRaises(ValueError):
            marker().score(b"short")

    def test_saved_markers_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "markers.json"
            self.assertEqual(load_markers(path), (None, None))
            save_markers(path, marker(), None)
            dialogue, gameplay = load_markers(path)
            self.assertEqual(dialogue.score(icon()), 1)
            self.assertIsNone(gameplay)
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_invalid_saved_coordinates_and_edges(self):
        data = marker().as_dict()
        data['x'] = -1
        with self.assertRaises(ValueError):
            Marker.from_dict(data)
        data = marker().as_dict()
        data['edges'] = [[-1, 24]] * 12
        with self.assertRaises(ValueError):
            Marker.from_dict(data)


@unittest.skipUnless(sys.platform == 'win32', 'Windows GDI only')
class NativeCaptureTests(unittest.TestCase):
    def test_gdi_capture_from_synthetic_bitmap_without_reading_desktop(self):
        api = app.Windows()
        source = api.create_dc(None)
        self.assertTrue(source)
        bitmap = previous = None
        try:
            info = app.BITMAPINFO()
            self.assertEqual(ctypes.sizeof(app.BITMAPINFOHEADER), 40)
            image_width, image_height = 57, 180
            info.bmiHeader = app.BITMAPINFOHEADER(
                biSize=40, biWidth=image_width, biHeight=-image_height,
                biPlanes=1, biBitCount=32)
            bits = ctypes.c_void_p()
            bitmap = api.create_bitmap(source, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
            self.assertTrue(bitmap)
            self.assertTrue(bits.value)
            previous = api.select_object(source, bitmap)
            self.assertTrue(previous)
            self.assertTrue(api.flush())
            sample = icon()
            pixels = bytearray(bytes((40, 40, 40, 0)) * image_width * image_height)
            for row in range(PATCH_SIZE):
                offset = ((row + 30) * image_width + 18) * 4
                pixels[offset:offset + PATCH_SIZE * 4] = sample[row * PATCH_SIZE * 4:(row + 1) * PATCH_SIZE * 4]
            pixels = bytes(pixels)
            ctypes.memmove(bits, pixels, len(pixels))
            # 用已生成的内存图像替代屏幕 DC，检验真实 BitBlt 和资源清理。
            api.get_dc = lambda _: source
            api.release_dc = lambda *_: 1
            api.foreground = lambda: 123
            api.size = lambda _: (image_width, image_height)
            api.to_screen = lambda *_: True
            captured = api.patch(123, image_width, image_height, 0, 0, image_width, image_height)
            self.assertEqual(len(captured), len(pixels))
            self.assertEqual([(x, y) for x, y, _ in marker().scan(captured, image_width, image_height, 0.9)], [(18, 30)])
            small = api.patch(123, image_width, image_height, 18, 30)
            self.assertEqual(marker().score(small), 1)
        finally:
            if previous:
                api.select_object(source, previous)
            if bitmap:
                api.delete_object(bitmap)
            api.delete_dc(source)


class GuardTests(unittest.TestCase):
    def test_close_stability_cooldown_and_disappearance(self):
        guard = CloseGuard(1.5)
        point = (123, 1920, 1080, 1800, 120)
        self.assertFalse(guard.update(0, point))
        self.assertFalse(guard.update(0.1, point))
        self.assertTrue(guard.update(0.2, point))
        self.assertFalse(guard.update(1.0, point))
        self.assertTrue(guard.update(1.7, point))
        self.assertFalse(guard.update(2.0, None))
        self.assertFalse(guard.update(2.1, None))
        self.assertFalse(guard.update(3.3, point))
        self.assertTrue(guard.update(3.5, point))

    def test_close_failed_three_times_reports_pause(self):
        guard = CloseGuard(1.5)
        point = (123, 1920, 1080, 1800, 120)
        self.assertFalse(guard.update(0, point))
        for now in (0.2, 1.7, 3.2):
            self.assertTrue(guard.update(now, point))
        with self.assertRaisesRegex(RuntimeError, '三次'):
            guard.update(4.7, point)
    def test_gameplay_mode_ignores_dialogue_animation_and_stops_on_hud(self):
        guard = StoryGuard(2, mode='gameplay')
        self.assertEqual(guard.update(0, False, False), 'active')
        self.assertEqual(guard.update(100, False, False), 'active')
        self.assertEqual(guard.update(101, True, True), 'ended')
        self.assertEqual(guard.update(102, True, False), 'ended')

    def test_missing_stops_input_immediately_and_confirms_later(self):
        guard = StoryGuard(2)
        self.assertEqual(guard.update(10, True), 'active')
        self.assertEqual(guard.update(11, False), 'hold')
        self.assertEqual(guard.update(12.9, False), 'hold')
        self.assertEqual(guard.update(13, False), 'ended')
        self.assertEqual(guard.update(14, True), 'ended')

    def test_transient_absence_and_timer_reset(self):
        guard = StoryGuard(2)
        self.assertEqual(guard.update(0, False), 'hold')
        self.assertEqual(guard.update(1.9, True), 'active')
        self.assertEqual(guard.update(2, False), 'hold')
        self.assertEqual(guard.update(3.9, False), 'hold')
        self.assertEqual(guard.update(4, False), 'ended')

    def test_gameplay_overrides_positive_dialogue_marker(self):
        guard = StoryGuard(2)
        self.assertEqual(guard.update(0, True, True), 'ended')
        self.assertEqual(guard.update(1, True, False), 'ended')


class FakeWindows:
    def __init__(self, frames, gameplay):
        self.frames, self.gameplay = frames, gameplay
        self.frame, self.reads = 0, 0
        self.actions = []
        self.bound_window = None

    def register_keys(self, keys):
        pass

    def hotkey_events(self):
        return self.frames[self.frame].get('keys', set())

    def key_state(self, vk):
        self.reads += 1
        if self.reads <= 9:  # 启动时的热键初始状态
            return 0
        key = {0x71: 'F2', 0x72: 'F3', 0x73: 'F4', 0x74: 'F5', 0x75: 'F6', 0x76: 'F7', 0x77: 'F8', 0x78: 'F9', 0x79: 'F10'}.get(vk)
        return 0x8000 if key in self.frames[self.frame].get('keys', set()) else 0

    def game_window(self, executables):
        if self.frames[self.frame].get('cloud') and self.bound_window is None:
            return None
        return self.frames[self.frame].get('hwnd', 123)

    def bind_foreground(self):
        self.bound_window = (123, 42)
        return 123, 1920, 1080

    def report_diagnostics(self, *args):
        app.say('[诊断] 测试窗口')

    def marker_visible(self, hwnd, template, threshold):
        if self.frames[self.frame].get('resize'):
            raise ValueError('分辨率已改变')
        field = 'gameplay' if template is self.gameplay else 'dialogue'
        return self.frames[self.frame].get(field, field == 'dialogue')

    def capture_marker(self, hwnd, neutral=True):
        sample = marker()
        sample.neutral = neutral
        return sample

    def find_option(self, hwnd, template, threshold):
        if isinstance(template, FixedPoint):
            return hwnd, template.width, template.height, template.x, template.y
        point = self.frames[self.frame].get('option')
        if not point:
            return None
        return hwnd, 1920, 1080, 1300, point if type(point) is int else 600

    def find_close(self, hwnd, templates, threshold):
        if self.frames[self.frame].get('resize'):
            raise ValueError('分辨率已改变')
        if self.frames[self.frame].get('close'):
            return hwnd, 1920, 1080, 1800, 120
        return None

    def capture_option(self, hwnd):
        return hwnd, 1920, 1080, 1300, 600

    def advance(self, hwnd, dry_run):
        self.actions.append(('space', self.frame))

    def press_key(self, hwnd, key, dry_run):
        self.actions.append((key, self.frame))

    def select_option(self, hwnd, option, action, dry_run):
        self.actions.append(('f' if action == 'f' else 'click', self.frame))

    def click_option(self, hwnd, option, dry_run):
        self.actions.append(('close' if option[3:] == (1800, 120) else 'click', self.frame))


class MainLoopTests(unittest.TestCase):
    def run_loop(self, frames, dialogue=None, option=None, mode='dialogue', gameplay_enabled=True, extra_args=(), close=False):
        gameplay = marker() if gameplay_enabled else None
        fake = FakeWindows(frames, gameplay)
        output = io.StringIO()
        with (patch.object(app, 'Windows', return_value=fake),
              patch.object(app, 'load_markers', return_value=(dialogue, gameplay)),
              patch.object(app, 'save_markers'),
              patch.object(app, 'load_option', return_value=option),
              patch.object(app, 'save_option'),
              patch.object(app, 'load_close_markers', return_value=[marker()] if close else []),
              patch.object(app, 'save_close_marker', side_effect=lambda path, items, candidate: [*items, candidate]),
              patch.object(app.time, 'monotonic', side_effect=lambda: fake.frame * 0.5),
              patch.object(app.time, 'sleep', side_effect=lambda _: setattr(fake, 'frame', fake.frame + 1)),
              patch.object(sys, 'argv', ['auto_story.py', '--end-mode', mode,
                                       '--option-mode', 'detect', '--option-key', 'mouse', '--interact-key', 'none', *extra_args]),
              contextlib.redirect_stdout(output)):
            app.main()
        return fake.actions, output.getvalue()

    def test_calibration_flicker_end_and_no_automatic_restart(self):
        frames = [
            {'keys': {'F8'}}, {'keys': {'F5'}}, {'keys': {'F7'}}, {},
            {'keys': {'F8'}}, {'option': True}, {'dialogue': False}, {}, {}, {'option': True},
            *[{'dialogue': False} for _ in range(5)], {},
            {'keys': {'F8'}}, {'gameplay': True}, {}, {'keys': {'F9'}},
        ]
        actions, output = self.run_loop(frames)
        self.assertEqual(actions, [('click', 5), ('space', 8), ('click', 9)])
        self.assertIn('请先在探索界面', output)
        self.assertIn('对白标记恢复', output)
        self.assertEqual(output.count('已自动暂停'), 2)

    def test_focus_loss_requires_manual_restart(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}}, {}, {'hwnd': None}, {},
            {'keys': {'F8'}}, {}, {'keys': {'F9'}},
        ], dialogue=marker())
        self.assertEqual(actions, [('space', 1), ('space', 5)])
        self.assertIn('游戏失去焦点', output)

    def test_resolution_change_stops_before_input(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}}, {'resize': True}, {}, {'keys': {'F9'}},
        ], dialogue=marker())
        self.assertEqual(actions, [])
        self.assertIn('分辨率已改变', output)

    def test_no_start_when_dialogue_absent_or_gameplay_present(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'dialogue': False}, {},
            {'keys': {'F8'}, 'gameplay': True}, {}, {'keys': {'F9'}},
        ], dialogue=marker())
        self.assertEqual(actions, [])
        self.assertEqual(output.count('不启动'), 2)

    def test_cloud_binding_preserves_calibration_and_focus_pause(self):
        frames = [
            {'keys': {'F8'}}, {'keys': {'F2'}}, {'keys': {'F8'}}, {},
            {'hwnd': None}, {}, {'keys': {'F8'}}, {}, {'keys': {'F9'}},
        ]
        for frame in frames:
            frame['cloud'] = True
        actions, output = self.run_loop(frames, dialogue=marker())
        self.assertEqual(actions, [('space', 3), ('space', 7)])
        self.assertIn('F2 绑定', output)
        self.assertIn('已绑定当前窗口', output)
        self.assertIn('保留同尺寸标定', output)

    def test_auto_mode_needs_no_f5_and_continues_during_hidden_dialogue(self):
        frames = [{'keys': {'F8'}}, {}, {}, {}, {}, {}, {'gameplay': True}, {}, {'keys': {'F9'}}]
        for frame in frames:
            frame['dialogue'] = False
        actions, output = self.run_loop(frames, mode='auto')
        self.assertEqual(actions, [('space', 1), ('space', 3), ('space', 5)])
        self.assertIn('探索界面恢复', output)
        self.assertEqual(output.count('已自动暂停'), 1)

    def test_automatic_options_move_and_are_not_clicked_when_absent(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}}, {'option': 550}, {}, {}, {}, {'option': 700}, {},
            {'gameplay': True}, {'option': 550}, {'keys': {'F9'}},
        ], option=marker(), mode='auto')
        self.assertEqual([frame for kind, frame in actions if kind == 'click'], [1, 5])
        self.assertEqual(output.count('已自动确认'), 2)

    def test_options_keep_dialogue_mode_running_when_dialogue_icon_hidden(self):
        frames = [{'keys': {'F8'}}, {}, {}, {}, {}, {}, {'keys': {'F9'}}]
        for frame in frames:
            frame.update(dialogue=False, option=550)
        actions, output = self.run_loop(frames, dialogue=marker(), option=marker(), gameplay_enabled=False)
        self.assertEqual([frame for kind, frame in actions if kind == 'click'], [1, 5])
        self.assertNotIn('已自动暂停', output)

    def test_diagnostics_does_not_send_input(self):
        actions, output = self.run_loop([{'keys': {'F10'}}, {}, {'keys': {'F9'}}])
        self.assertEqual(actions, [])
        self.assertIn('[诊断]', output)

    def test_npc_f_once_waits_for_dialogue_then_space_and_f_until_end(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'gameplay': True}, {'gameplay': True}, {}, {}, {}, {}, {}, {},
            {'gameplay': True}, {}, {'keys': {'F9'}},
        ], mode='auto', extra_args=('--option-mode', 'fixed', '--option-key', 'f', '--interact-key', 'f'))
        self.assertEqual(actions, [('f', 0), ('f', 4), ('space', 5), ('space', 7)])
        self.assertIn('已按 F 开始交互', output)
        self.assertIn('已进入对白', output)
        self.assertIn('已自动暂停', output)

    def test_npc_interaction_timeout_does_not_spam_f_or_auto_restart(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'gameplay': True}, {'gameplay': True}, {'gameplay': True}, {}, {'keys': {'F9'}},
        ], mode='auto', extra_args=('--option-mode', 'fixed', '--option-key', 'f', '--interact-key', 'f', '--interaction-timeout', '0.6'))
        self.assertEqual(actions, [('f', 0)])
        self.assertIn('F 交互后未进入对白，已暂停', output)

    def test_focus_loss_during_npc_opening_stops_wait(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'gameplay': True}, {'hwnd': None}, {}, {}, {'keys': {'F9'}},
        ], mode='auto', extra_args=('--option-mode', 'fixed', '--option-key', 'f', '--interact-key', 'f'))
        self.assertEqual(actions, [('f', 0)])
        self.assertIn('游戏失去焦点', output)

    def test_capture_error_during_opening_cancels_wait(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'gameplay': True}, {'resize': True}, {}, {}, {}, {'keys': {'F9'}},
        ], mode='auto', extra_args=('--option-mode', 'fixed', '--option-key', 'f', '--interact-key', 'f'))
        self.assertEqual(actions, [('f', 0)])
        self.assertIn('已暂停：分辨率已改变', output)
        self.assertNotIn('已进入对白', output)

    def test_fixed_coordinate_is_not_evidence_of_dialogue(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}}, *[{'dialogue': False} for _ in range(5)], {'keys': {'F9'}},
        ], dialogue=marker(), option=FixedPoint(1920, 1080, 1300, 600), gameplay_enabled=False,
           extra_args=('--option-mode', 'fixed', '--option-key', 'f'))
        self.assertEqual(actions, [])
        self.assertIn('已自动暂停', output)

    def test_fixed_f7_calibration_does_not_require_white_icon(self):
        actions, output = self.run_loop([
            {'keys': {'F7'}}, {'keys': {'F8'}}, {}, {'gameplay': True}, {'keys': {'F9'}},
        ], mode='auto', extra_args=('--option-mode', 'fixed', '--option-key', 'f'))
        self.assertEqual(actions, [('f', 2)])
        self.assertIn('已保存固定选项位置', output)

    def test_close_has_priority_and_dialogue_resumes_after_popup_gone(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'close': True}, {'close': True}, {'close': True}, {}, {},
            {'gameplay': True}, {}, {'keys': {'F9'}},
        ], mode='auto', close=True)
        self.assertEqual(actions, [('close', 2), ('space', 4)])
        self.assertIn('优先点击关闭按钮', output)

    def test_close_works_during_five_second_end_cleanup(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}}, {}, {'gameplay': True}, {'gameplay': True, 'close': True},
            {'gameplay': True, 'close': True}, {'gameplay': True}, {}, {'keys': {'F9'}},
        ], mode='auto', close=True)
        self.assertEqual(actions, [('space', 1), ('close', 4)])
        self.assertIn('收尾 5 秒', output)

    def test_manual_pause_disables_close_detection(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'close': True}, {'close': True}, {'keys': {'F8'}, 'close': True},
            {'close': True}, {'close': True}, {'keys': {'F9'}},
        ], mode='auto', close=True)
        self.assertEqual(actions, [])
        self.assertIn('已暂停', output)

    def test_focus_loss_blocks_close_click(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'close': True}, {'close': True}, {'hwnd': None, 'close': True},
            {'close': True}, {'keys': {'F9'}},
        ], mode='auto', close=True)
        self.assertEqual(actions, [])
        self.assertIn('游戏失去焦点', output)

    def test_close_cleanup_expiry_does_not_click_later_popup(self):
        frames = [{'keys': {'F8'}}, {}, {'gameplay': True}, *[{} for _ in range(10)],
                  {'close': True}, {'close': True}, {'keys': {'F9'}}]
        actions, _ = self.run_loop(frames, mode='auto', close=True)
        self.assertEqual(actions, [('space', 1)])

    def test_f3_calibration_is_saved_but_does_not_click_while_paused(self):
        actions, output = self.run_loop([{'keys': {'F3'}, 'close': True}, {'close': True}, {'keys': {'F9'}}])
        self.assertEqual(actions, [])
        self.assertIn('已保存 × 关闭按钮', output)

    def test_no_auto_close_flag_keeps_normal_dialogue_behaviour(self):
        actions, output = self.run_loop([
            {'keys': {'F8'}, 'close': True}, {'close': True}, {'gameplay': True}, {'keys': {'F9'}},
        ], mode='auto', close=True, extra_args=('--no-auto-close',))
        self.assertEqual(actions, [('space', 1)])

    def test_close_click_failure_stops_instead_of_retrying_forever(self):
        frames = [{'keys': {'F8'}, 'close': True}, *[{'close': True} for _ in range(12)], {'keys': {'F9'}}]
        actions, output = self.run_loop(frames, mode='auto', close=True)
        self.assertEqual(actions, [('close', 2), ('close', 5), ('close', 8)])
        self.assertIn('三次后仍存在，已暂停', output)


class BindingAndInputTests(unittest.TestCase):
    def test_close_search_returns_visual_position_and_ignores_absent_icon(self):
        api = object.__new__(app.Windows)
        template = Marker.calibrate(1920, 1080, 1800, 90, close_icon(), neutral=False)
        width = height = 89
        image = bytearray(bytes((40, 40, 40, 0)) * width * height)
        sample = close_icon()
        for y in range(PATCH_SIZE):
            offset = ((40 + y) * width + 40) * 4
            image[offset:offset + PATCH_SIZE * 4] = sample[y * PATCH_SIZE * 4:(y + 1) * PATCH_SIZE * 4]
        api.patch = lambda *args: bytes(image)
        self.assertEqual(api.find_close(123, [template], 0.92), (123, 1920, 1080, 1820, 110))
        api.patch = lambda *args: bytes((40, 40, 40, 0)) * width * height
        self.assertIsNone(api.find_close(123, [template], 0.92))
    def test_f_key_uses_its_own_scan_code_and_is_released(self):
        api = object.__new__(app.Windows)
        api.foreground = lambda: 123
        events = []
        api.inject = lambda batch: events.extend((e.ki.wScan, e.ki.dwFlags) for e in batch)
        with patch.object(app.time, 'sleep'):
            api.press_key(123, 'f', False)
        self.assertEqual(events, [(0x21, 8), (0x21, 10)])

    def test_fixed_point_selects_f_without_mouse_click(self):
        api = object.__new__(app.Windows)
        api.foreground = lambda: 123
        api.size = lambda hwnd: (1920, 1080)
        api.to_screen = lambda *args: True
        moved, events = [], []
        api.move = lambda x, y: moved.append((x, y)) or 1
        api.inject = lambda batch: events.extend((e.type, e.ki.wScan, e.ki.dwFlags) for e in batch)
        with patch.object(app.time, 'sleep'):
            api.select_option(123, (123, 1920, 1080, 1300, 600), 'f', False)
        self.assertEqual(moved, [(1300, 600)])
        self.assertEqual(events, [(1, 0x21, 8), (1, 0x21, 10)])

    def test_find_option_returns_actual_top_row_instead_of_saved_y(self):
        api = object.__new__(app.Windows)
        template = marker()
        template.neutral = False
        template.y = 400
        width, height = 57, 756
        def region_at(row):
            image = bytearray(bytes((40, 40, 40, 0)) * width * height)
            sample = icon()
            for target_y in (row, row + 100):
                for y in range(PATCH_SIZE):
                    offset = ((target_y + y) * width + 16) * 4
                    image[offset:offset + PATCH_SIZE * 4] = sample[y * PATCH_SIZE * 4:(y + 1) * PATCH_SIZE * 4]
            return bytes(image)
        api.patch = lambda *args: region_at(150)
        self.assertEqual(api.find_option(123, template, 0.9), (123, 1920, 1080, 112, 378))
        api.patch = lambda *args: region_at(300)
        self.assertEqual(api.find_option(123, template, 0.9), (123, 1920, 1080, 112, 528))
        api.patch = lambda *args: bytes((40, 40, 40, 0)) * width * height
        self.assertIsNone(api.find_option(123, template, 0.9))
    def test_hotkey_registration_consumes_browser_function_keys(self):
        api = object.__new__(app.Windows)
        api.hotkeys = {}
        registered, released = [], []
        api.register_hotkey = lambda hwnd, identifier, modifiers, vk: registered.append((identifier, modifiers, vk)) or 1
        api.unregister_hotkey = lambda hwnd, identifier: released.append(identifier) or 1
        with patch.object(app.atexit, 'register'):
            api.register_keys({'F2': 0x71, 'F5': 0x74})
        self.assertEqual(registered, [(0x71, 0x4000, 0x71), (0x74, 0x4000, 0x74)])
        pending = [0x74, 0x71]
        def peek(pointer, hwnd, low, high, remove):
            self.assertEqual((low, high, remove), (0x312, 0x312, 1))
            if not pending:
                return 0
            ctypes.cast(pointer, ctypes.POINTER(app.MSG)).contents.wParam = pending.pop(0)
            return 1
        api.peek_message = peek
        self.assertEqual(api.hotkey_events(), {'F5', 'F2'})
        self.assertEqual(api.hotkey_events(), set())
        api.unregister_keys()
        self.assertEqual(released, [0x71, 0x74])

    def test_hotkey_conflict_rolls_back_and_reports_failure(self):
        api = object.__new__(app.Windows)
        api.hotkeys = {}
        api.register_hotkey = lambda hwnd, identifier, modifiers, vk: vk != 0x74
        released = []
        api.unregister_hotkey = lambda hwnd, identifier: released.append(identifier) or 1
        with patch.object(app.atexit, 'register'):
            with self.assertRaisesRegex(RuntimeError, '无法注册 F5'):
                api.register_keys({'F2': 0x71, 'F5': 0x74})
        self.assertEqual(released, [0x71])
        self.assertEqual(api.hotkeys, {})

    def test_binding_checks_window_and_pid_without_reading_executable(self):
        api = object.__new__(app.Windows)
        api.bound_window = None
        current = {'hwnd': 123, 'pid': 42}
        api.foreground = lambda: current['hwnd']
        api.size = lambda _: (1920, 1080)
        def pid(hwnd, pointer):
            ctypes.cast(pointer, ctypes.POINTER(app.W.DWORD)).contents.value = current['pid']
            return 1
        api.pid = pid
        self.assertEqual(api.bind_foreground(), (123, 1920, 1080))
        self.assertEqual(api.game_window(set()), 123)
        current['hwnd'] = 456
        self.assertIsNone(api.game_window(set()))
        current['hwnd'], current['pid'] = 123, 43
        self.assertIsNone(api.game_window(set()))
        current['pid'] = 42
        self.assertEqual(api.game_window(set()), 123)

    def test_space_uses_scan_code_and_distinct_down_hold_up(self):
        api = object.__new__(app.Windows)
        api.foreground = lambda: 123
        events = []
        api.inject = lambda batch: events.extend((e.ki.wScan, e.ki.dwFlags) for e in batch)
        with patch.object(app.time, 'sleep', side_effect=lambda delay: events.append(('hold', delay))):
            api.advance(123, False)
        self.assertEqual(events, [(0x39, 8), ('hold', 0.08), (0x39, 10)])

    def test_interrupted_hold_still_releases_space(self):
        api = object.__new__(app.Windows)
        api.foreground = lambda: 123
        events = []
        api.inject = lambda batch: events.extend(e.ki.dwFlags for e in batch)
        with patch.object(app.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                api.advance(123, False)
        self.assertEqual(events, [8, 10])

    def test_no_injection_for_dry_run_or_lost_focus(self):
        api = object.__new__(app.Windows)
        api.foreground = lambda: 123
        api.inject = lambda _: self.fail('Unexpected real input')
        with contextlib.redirect_stdout(io.StringIO()):
            api.advance(123, True)
        api.advance(456, False)


if __name__ == '__main__':
    unittest.main()
