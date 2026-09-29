"""core/notifications.py (the Qt-free history) and ui/notification_center.py (bell button, panel, toast popups)."""
from PySide6.QtWidgets import QMainWindow

from anihub.core.notifications import NotificationCenter
from anihub.ui.notification_center import NotificationSignals, NotificationsButton, NotificationsDialog, ToastHost


def test_notify_adds_newest_first():
    center = NotificationCenter()
    center.notify("a", "1")
    center.notify("b", "2")
    assert [n.title for n in center.all()] == ["b", "a"]


def test_unread_count_and_mark_all_read():
    center = NotificationCenter()
    center.notify("a", "1")
    center.notify("b", "2")
    assert center.unread_count() == 2
    center.mark_all_read()
    assert center.unread_count() == 0
    assert all(n.read for n in center.all())


def test_clear_empties_the_history():
    center = NotificationCenter()
    center.notify("a", "1")
    center.clear()
    assert center.all() == []


def test_history_is_capped():
    center = NotificationCenter()
    center.MAX_HISTORY = 3
    for i in range(5):
        center.notify(str(i), "")
    assert len(center.all()) == 3
    assert [n.title for n in center.all()] == ["4", "3", "2"]


def test_on_notify_and_on_change_callbacks_fire():
    center = NotificationCenter()
    posted, changed = [], []
    center.on_notify = posted.append
    center.on_change = lambda: changed.append(1)
    center.notify("a", "1")
    assert len(posted) == 1 and posted[0].title == "a"
    assert len(changed) == 1
    center.mark_all_read()
    assert len(changed) == 2
    center.clear()
    assert len(changed) == 3


def test_mark_all_read_and_clear_are_no_ops_on_an_empty_or_already_read_history():
    """No spurious on_change firing when there is nothing to change."""
    center = NotificationCenter()
    changed = []
    center.on_change = lambda: changed.append(1)
    center.clear()               # nothing to clear
    center.mark_all_read()       # nothing to mark
    assert changed == []


def test_notifications_button_hidden_until_something_is_posted(qapp):
    center = NotificationCenter()
    signals = NotificationSignals()
    center.on_notify, center.on_change = signals.posted.emit, signals.changed.emit
    ctx = type("Ctx", (), {"notifications": center})()
    btn = NotificationsButton(ctx, signals)
    assert btn.isHidden() or not btn.isVisible()
    center.notify("a", "1")
    assert btn.text() == "1"


def test_notifications_button_marks_read_on_open_and_clears_badge(qapp):
    center = NotificationCenter()
    signals = NotificationSignals()
    center.on_notify, center.on_change = signals.posted.emit, signals.changed.emit
    ctx = type("Ctx", (), {"notifications": center})()
    win = QMainWindow()
    btn = NotificationsButton(ctx, signals, win)
    center.notify("a", "1")
    assert btn.text() == "1"
    btn.open_panel()
    assert btn._dialog is not None
    assert btn.text() == ""            # mark_all_read() fired via open_panel()
    btn._dialog.close()
    win.close()


def test_notifications_dialog_lists_entries_and_clear_empties_it(qapp):
    center = NotificationCenter()
    signals = NotificationSignals()
    center.on_notify, center.on_change = signals.posted.emit, signals.changed.emit
    ctx = type("Ctx", (), {"notifications": center})()
    center.notify("Title", "Body text")
    dlg = NotificationsDialog(ctx, signals)
    assert dlg.list.count() == 1
    assert "Title" in dlg.list.item(0).text()
    dlg._clear()
    assert dlg.list.count() == 1  # the "nothing yet" placeholder row
    dlg.close()


def test_toast_host_shows_and_dismisses_a_popup(qapp):
    win = QMainWindow()
    win.resize(600, 400)
    host = ToastHost(win)
    from anihub.core.notifications import Notification

    item = Notification(1, "Hello", "World", "info")
    host.show_toast(item)
    assert len(host._toasts) == 1
    frame = host._toasts[0]
    assert frame.parent() is win
    host._dismiss(frame)
    assert host._toasts == []
    win.close()
