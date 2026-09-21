"""The extensions dialog: repositories, the sources they offer, install / update / remove, and the settings of installed ones."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.extensions import ExtensionError, ExtensionManager, ExtInfo
from anihub.ui import style
from anihub.ui.lang_filter import lang_name
from anihub.ui.workers import run_async


class ReposDialog(QDialog):
    """Add / remove repository addresses."""

    def __init__(self, manager: ExtensionManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle(tr("ext.repos"))
        self.resize(640, 320)
        self.list = QListWidget()
        self.list.addItems(manager.repos())
        add, remove = style.secondary(QPushButton(tr("ext.repo_add")), "plus"), style.secondary(QPushButton(tr("ext.repo_remove")), "x")
        hint = style.role(QLabel(tr("ext.repo_hint")), "dim")
        hint.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)

    def _add(self) -> None:
        url, ok = QInputDialog.getText(self, tr("ext.repo_add"), tr("ext.repo_url"))
        if ok and url.strip().startswith(("http://", "https://")):
            self.list.addItem(url.strip())
            self._save()

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._save()

    def _save(self) -> None:
        self.manager.set_repos([self.list.item(i).text() for i in range(self.list.count())])


class PluginSettingsDialog(QDialog):
    """The fields a source declares in `credentials` (login, cookie, server address...)."""

    def __init__(self, ctx: AppContext, source, parent=None):
        super().__init__(parent)
        self.ctx, self.source = ctx, source
        self.setWindowTitle(f"{source.title} — {tr('ext.settings')}")
        self.fields = {key: QLineEdit(str(ctx.cfg.get(f"sources.{source.name}.{key}") or "")) for key, _ in source.credentials}
        form = QFormLayout()
        for key, label in source.credentials:
            form.addRow(label, self.fields[key])
        save = style.primary(QPushButton(tr("settings.save")), "check")
        save.clicked.connect(self._save)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(save, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(520, 40 + 44 * len(self.fields))

    def _save(self) -> None:
        for key, field in self.fields.items():
            self.ctx.cfg.set(f"sources.{self.source.name}.{key}", field.text().strip(), save=False)
        self.ctx.cfg.save()
        self.accept()


class ExtensionsDialog(QDialog):
    """`kinds`: which extension kinds to show ("anime", "novel")."""

    def __init__(self, ctx: AppContext, manager: ExtensionManager, kinds: tuple[str, ...], installed_sources, parent=None):
        super().__init__(parent)
        self.ctx, self.manager, self.kinds = ctx, manager, kinds
        self.installed_sources = installed_sources          # callable -> {name: source} of the running sources of these kinds
        self.changed = False
        self._infos: list[ExtInfo] = []
        self.setWindowTitle(tr("ext.title"))
        self.resize(820, 520)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("ext.col.name"), tr("ext.col.lang"), tr("ext.col.version"), tr("ext.col.state")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 90)
        self.info = style.role(QLabel(), "dim")
        self.info.setWordWrap(True)
        self.message = style.role(QLabel(), "dim")
        self.message.setWordWrap(True)
        self.install_btn = style.primary(QPushButton(tr("ext.install")), "download")
        self.remove_btn = style.secondary(QPushButton(tr("ext.remove")), "trash")
        self.config_btn = style.secondary(QPushButton(tr("ext.settings")), "sliders")
        self.repos_btn = style.secondary(QPushButton(tr("ext.repos")), "external")
        self.refresh_btn = style.ghost(QPushButton(tr("ext.refresh")), "refresh")
        row = QHBoxLayout()
        for w in (self.install_btn, self.remove_btn, self.config_btn):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.repos_btn)
        row.addWidget(self.refresh_btn)
        warning = style.role(QLabel(tr("ext.warning")), "dim")
        warning.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.info)
        layout.addLayout(row)
        layout.addWidget(warning)
        layout.addWidget(self.message)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.install_btn.clicked.connect(self._install)
        self.remove_btn.clicked.connect(self._remove)
        self.config_btn.clicked.connect(self._configure)
        self.repos_btn.clicked.connect(self._repos)
        self.refresh_btn.clicked.connect(self.refresh)
        self._selection()
        self.refresh()

    # --- list --------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        self.message.setText(tr("status.loading"))
        self.refresh_btn.setEnabled(False)

        def done(result) -> None:
            infos, errors = result
            self.refresh_btn.setEnabled(True)
            self._infos = [i for i in infos if i.kind in self.kinds]
            self._fill()
            self.message.setText("\n".join(errors) if errors else tr("ext.found", n=len(self._infos)))

        run_async(self.manager.available, on_done=done,
                  on_error=lambda exc: (self.refresh_btn.setEnabled(True), self.message.setText(tr("status.error", msg=str(exc)))))

    def _fill(self) -> None:
        self.tree.clear()
        for info in self._infos:
            state = {"new": "", "installed": "✓ " + tr("ext.installed"), "update": "↑ " + tr("ext.update")}[self.manager.status(info)]
            item = QTreeWidgetItem([info.name + ("  18+" if info.nsfw else ""), lang_name(info.lang), info.version, state])
            item.setData(0, Qt.ItemDataRole.UserRole, info)
            self.tree.addTopLevelItem(item)

    def _current(self) -> ExtInfo | None:
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _selection(self) -> None:
        info = self._current()
        status = self.manager.status(info) if info else ""
        self.info.setText(info.description if info else "")
        self.install_btn.setEnabled(info is not None and status in ("new", "update"))
        self.install_btn.setText(tr("ext.update") if status == "update" else tr("ext.install"))
        self.remove_btn.setEnabled(status in ("installed", "update"))
        self.config_btn.setEnabled(self._source_of(info) is not None and bool(self._source_of(info).credentials))

    def _source_of(self, info: ExtInfo | None):
        if info is None:
            return None
        return next((s for s in self.installed_sources().values() if type(s).__module__.endswith(f"_{info.id}")), None)

    # --- actions -----------------------------------------------------------------------------------------------

    def _install(self) -> None:
        info = self._current()
        if info is None:
            return
        if QMessageBox.question(self, tr("ext.install"), tr("ext.confirm", name=info.name, repo=info.repo)) != QMessageBox.StandardButton.Yes:
            return
        self.message.setText(tr("status.loading"))

        def done(_path) -> None:
            self.changed = True
            self.ctx.reload_extensions()
            self._fill()
            self._selection()
            self.message.setText(tr("ext.done", name=info.name))

        run_async(lambda: self.manager.install(info), on_done=done, on_error=lambda exc: self.message.setText(str(exc)))

    def _remove(self) -> None:
        info = self._current()
        if info is None:
            return
        self.manager.uninstall(info.kind, info.id)
        self.changed = True
        self.ctx.reload_extensions()
        self._fill()
        self._selection()

    def _configure(self) -> None:
        source = self._source_of(self._current())
        if source is not None:
            PluginSettingsDialog(self.ctx, source, self).exec()

    def _repos(self) -> None:
        ReposDialog(self.manager, self).exec()
        self.refresh()
