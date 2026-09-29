"""core/undo.py: the tiny app-level undo/redo stack, independent of any UI."""
from anihub.core.undo import UndoStack


def test_push_then_undo_calls_the_undo_callable():
    stack = UndoStack()
    calls = []
    stack.push("trash 1 item", lambda: calls.append("undo"), lambda: calls.append("redo"))
    assert stack.can_undo() and not stack.can_redo()
    label = stack.undo()
    assert label == "trash 1 item"
    assert calls == ["undo"]
    assert not stack.can_undo() and stack.can_redo()


def test_redo_calls_the_redo_callable():
    stack = UndoStack()
    calls = []
    stack.push("x", lambda: calls.append("undo"), lambda: calls.append("redo"))
    stack.undo()
    label = stack.redo()
    assert label == "x"
    assert calls == ["undo", "redo"]
    assert stack.can_undo() and not stack.can_redo()


def test_undo_and_redo_on_an_empty_stack_return_none_and_do_nothing():
    stack = UndoStack()
    assert stack.undo() is None
    assert stack.redo() is None


def test_a_new_push_clears_the_redo_stack():
    stack = UndoStack()
    stack.push("a", lambda: None, lambda: None)
    stack.undo()
    assert stack.can_redo()
    stack.push("b", lambda: None, lambda: None)
    assert not stack.can_redo()


def test_history_is_capped_at_max():
    stack = UndoStack()
    stack.MAX = 3
    for i in range(5):
        stack.push(str(i), lambda: None, lambda: None)
    assert len(stack._undo) == 3
    assert [e.label for e in stack._undo] == ["2", "3", "4"]


def test_on_change_fires_on_push_undo_and_redo():
    stack = UndoStack()
    changes = []
    stack.on_change = lambda: changes.append(1)
    stack.push("a", lambda: None, lambda: None)
    stack.undo()
    stack.redo()
    assert len(changes) == 3
