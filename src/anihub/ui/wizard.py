"""First-run setup wizard: language, theme, library folder, ratings, system check."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget, QWizard, QWizardPage,
)

from anihub.core.config import Config
from anihub.core.i18n import set_language, tr
from anihub.services import sysreq
from anihub.sources.base import RATINGS
from anihub.ui.theme import apply_theme


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".anihub_write_test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


class LanguagePage(QWizardPage):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.setTitle("AniHUB — Welcome / Добро пожаловать")
        self.setSubTitle("Language / Язык, Theme / Тема")
        form = QFormLayout(self)
        self.lang = QComboBox()
        self.lang.addItem("Русский", "ru")
        self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(0 if cfg.get("language") == "ru" else 1)
        self.theme = QComboBox()
        for key in ("system", "light", "dark"):
            self.theme.addItem(key, key)
        self.theme.setCurrentIndex(0)
        form.addRow("Language / Язык", self.lang)
        form.addRow("Theme / Тема", self.theme)
        self.theme.currentIndexChanged.connect(self._preview_theme)

    def _preview_theme(self) -> None:
        apply_theme(QApplication.instance(), self.theme.currentData())

    def validatePage(self) -> bool:
        self.cfg.set("language", self.lang.currentData(), save=False)
        self.cfg.set("theme", self.theme.currentData(), save=False)
        set_language(self.lang.currentData())
        return True


class LibraryPage(QWizardPage):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.edit = QLineEdit(str(Path(cfg.get("library_path") or Path.home() / "AniHUB")))
        self.browse = QPushButton()
        self.info = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.edit)
        row.addWidget(self.browse)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addLayout(row)
        layout.addWidget(self.info)
        self.browse.clicked.connect(self._pick)
        self.edit.textChanged.connect(self._refresh)

    def initializePage(self) -> None:
        self.setTitle(tr("wizard.p2.title"))
        self.label.setText(tr("wizard.p2.text"))
        self.browse.setText(tr("wizard.browse"))
        self._refresh()

    def _pick(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("wizard.p2.title"), self.edit.text())
        if folder:
            self.edit.setText(os.path.normpath(folder))

    def _refresh(self) -> None:
        if self.edit.text().strip():
            free = sysreq.check_disk(self.edit.text().strip()).value
            self.info.setText(tr("wizard.p2.free", gb=free))
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return bool(self.edit.text().strip())

    def validatePage(self) -> bool:
        path = Path(self.edit.text().strip())
        if not _writable(path):
            self.info.setText(tr("wizard.p2.bad"))
            return False
        self.cfg.set("library_path", str(path), save=False)
        return True


class RatingPage(QWizardPage):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        self.boxes = {r: QCheckBox() for r in RATINGS}
        for box in self.boxes.values():
            layout.addWidget(box)

    def initializePage(self) -> None:
        self.setTitle(tr("wizard.p3.title"))
        self.label.setText(tr("wizard.p3.text"))
        allowed = set(self.cfg.get("ratings.allowed", ["general"]))
        for r, box in self.boxes.items():
            box.setText(tr(f"rating.{r}"))
            box.setChecked(r in allowed)

    def validatePage(self) -> bool:
        chosen = [r for r, box in self.boxes.items() if box.isChecked()] or ["general"]
        self.cfg.set("ratings.allowed", chosen, save=False)
        return True


class SystemPage(QWizardPage):
    def __init__(self, cfg: Config, library_page: LibraryPage):
        super().__init__()
        self.library_page = library_page
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.report = QLabel()
        self.report.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.report)

    def initializePage(self) -> None:
        self.setTitle(tr("wizard.p4.title"))
        self.label.setText(tr("wizard.p4.text"))
        lines = []
        java = sysreq.check_java()
        lines.append(("✔ " if java.ok else "✖ ") + (tr("sys.java.ok", d=java.detail) if java.ok else tr("sys.java.no")))
        gpu = sysreq.check_gpu()
        if not gpu.ok:
            lines.append("✖ " + tr("sys.gpu.no"))
        elif gpu.value < 6:
            lines.append("⚠ " + tr("sys.gpu.low", d=gpu.detail))
        else:
            lines.append("✔ " + tr("sys.gpu.ok", d=gpu.detail))
        disk = sysreq.check_disk(self.library_page.edit.text())
        lines.append(("✔ " + tr("sys.disk.ok", gb=disk.value)) if disk.ok else ("⚠ " + tr("sys.disk.low", gb=disk.value)))
        self.report.setText("\n\n".join(lines))


class DonePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.label = QLabel()
        self.label.setWordWrap(True)
        QVBoxLayout(self).addWidget(self.label)

    def initializePage(self) -> None:
        self.setTitle(tr("wizard.p5.title"))
        self.label.setText(tr("wizard.p5.text"))


class SetupWizard(QWizard):
    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("AniHUB")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)  # plain labels: follows the theme like everything else
        self.setMinimumSize(660, 460)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        for button, key in ((QWizard.WizardButton.BackButton, "wizard.back"), (QWizard.WizardButton.NextButton, "wizard.next"),
                            (QWizard.WizardButton.FinishButton, "wizard.finish"), (QWizard.WizardButton.CancelButton, "wizard.cancel")):
            self.setButtonText(button, tr(key))
        library_page = LibraryPage(cfg)
        for page in (LanguagePage(cfg), library_page, RatingPage(cfg), SystemPage(cfg, library_page), DonePage()):
            self.addPage(page)

    def initializePage(self, page_id: int) -> None:  # noqa: N802
        super().initializePage(page_id)
        for button in (QWizard.WizardButton.NextButton, QWizard.WizardButton.FinishButton):
            b = self.button(button)
            b.setProperty("variant", "primary")  # the forward button is the main action
            b.style().unpolish(b)
            b.style().polish(b)

    def accept(self) -> None:
        self.cfg.set("first_run_done", True, save=False)
        self.cfg.save()
        super().accept()
