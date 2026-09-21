"""First-run setup wizard: language, theme, library folder, ratings, system check."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QRadioButton, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget, QWizard, QWizardPage,
)

from anihub.core import agemode
from anihub.core.config import Config
from anihub.core.i18n import LANGUAGES, set_language, tr
from anihub.services import forge_install, sysreq
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
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(self.lang.findData(cfg.get("language")), 0))
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
        self.boxes = {m: QRadioButton() for m in agemode.MODES}
        for box in self.boxes.values():
            layout.addWidget(box)

    def initializePage(self) -> None:
        self.setTitle(tr("wizard.p3.title"))
        self.label.setText(tr("wizard.p3.text"))
        current = agemode.mode_of(self.cfg)
        for mode, box in self.boxes.items():
            box.setText(tr(f"wizard.p3.{mode}"))
            box.setChecked(mode == current)

    def chosen(self) -> str:
        return next((m for m, box in self.boxes.items() if box.isChecked()), agemode.DEFAULT_MODE)

    def validatePage(self) -> bool:
        agemode.apply_mode(self.cfg, self.chosen(), save=False)
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
        disk = sysreq.check_disk(self.library_page.edit.text())
        lines.append(("✔ " + tr("sys.disk.ok", gb=disk.value)) if disk.ok else ("⚠ " + tr("sys.disk.low", gb=disk.value)))
        self.report.setText("\n\n".join(lines))


class ForgePage(QWizardPage):
    """Does this computer suit Stable Diffusion Forge? If yes: download it, point to an installed one, or decide later.
    If not, the whole generation section is switched off (config `sd.enabled`)."""

    def __init__(self, cfg: Config, library_page: LibraryPage):
        super().__init__()
        self.cfg, self.library_page = cfg, library_page
        self.assessment: sysreq.ForgeAssessment | None = None
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.report = QLabel()
        self.report.setWordWrap(True)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.download = QRadioButton()
        self.existing = QRadioButton()
        self.later = QRadioButton()
        group = QButtonGroup(self)
        for b in (self.download, self.existing, self.later):
            group.addButton(b)
        self.install_dir = QLineEdit(str(Path.home() / "AniHUB-Forge"))
        self.existing_dir = QLineEdit(str(cfg.get("forge.path") or ""))
        self.install_browse = QPushButton()
        self.existing_browse = QPushButton()
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.options = QWidget()
        grid = QVBoxLayout(self.options)
        grid.setContentsMargins(0, 0, 0, 0)
        for radio, edit, browse in ((self.download, self.install_dir, self.install_browse),
                                    (self.existing, self.existing_dir, self.existing_browse)):
            grid.addWidget(radio)
            row = QHBoxLayout()
            row.setContentsMargins(26, 0, 0, 0)
            row.addWidget(edit, 1)
            row.addWidget(browse)
            grid.addLayout(row)
        grid.addWidget(self.later)
        layout = QVBoxLayout(self)
        for w in (self.label, self.report, self.verdict, self.options, self.hint):
            layout.addWidget(w)
        self.install_browse.clicked.connect(lambda: self._browse(self.install_dir))
        self.existing_browse.clicked.connect(lambda: self._browse(self.existing_dir))
        for b in (self.download, self.existing, self.later):
            b.toggled.connect(self._sync)

    def _browse(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("wizard.browse"), edit.text())
        if folder:
            edit.setText(os.path.normpath(folder))

    def _sync(self) -> None:
        self.install_dir.setEnabled(self.download.isChecked())
        self.install_browse.setEnabled(self.download.isChecked())
        self.existing_dir.setEnabled(self.existing.isChecked())
        self.existing_browse.setEnabled(self.existing.isChecked())

    def initializePage(self) -> None:
        self.setTitle(tr("wizard.forge.title"))
        self.label.setText(tr("wizard.forge.text"))
        for b, key in ((self.download, "wizard.forge.download"), (self.existing, "wizard.forge.existing"),
                       (self.later, "wizard.forge.later")):
            b.setText(tr(key))
        self.install_browse.setText(tr("wizard.browse"))
        self.existing_browse.setText(tr("wizard.browse"))
        a = self.assessment = sysreq.assess_forge(self.install_dir.text())
        lines = [("✔ " if a.vram_gb >= sysreq.MIN_VRAM_GB else "✖ ") + (tr("sys.forge.gpu", d=a.gpu, gb=f"{a.vram_gb:.0f}") if a.gpu else tr("sys.forge.no_gpu")),
                 ("✔ " if a.ram_gb >= sysreq.MIN_RAM_GB or not a.ram_gb else "✖ ") + tr("sys.forge.ram", gb=f"{a.ram_gb:.0f}"),
                 ("✔ " if a.disk_gb >= sysreq.MIN_DISK_GB else "⚠ ") + tr("sys.forge.disk", gb=f"{a.disk_gb:.0f}")]
        self.report.setText("\n".join(lines))
        weak = "\n".join("• " + tr(p) for p in a.problems)
        if not a.suitable:
            self.verdict.setText(tr("wizard.forge.no") + "\n" + weak)
        elif a.level == "low":
            self.verdict.setText(tr("wizard.forge.low") + "\n" + weak)
        else:
            self.verdict.setText(tr("wizard.forge.ok"))
        self.options.setVisible(a.suitable)
        self.hint.setText(tr("wizard.forge.rtx50") if "RTX 50" in a.gpu.upper() else "")
        self.download.setChecked(True)
        self._sync()

    def validatePage(self) -> bool:
        a = self.assessment
        if a is None or not a.suitable:
            self.cfg.set("sd.enabled", False, save=False)               # no generation on this computer: the section is hidden
            return True
        self.cfg.set("sd.enabled", True, save=False)
        if self.existing.isChecked():
            path = forge_install.forge_path_of(self.existing_dir.text().strip()) if self.existing_dir.text().strip() else None
            if path is None:
                self.hint.setText(tr("wizard.forge.bad_folder"))
                return False
            self.cfg.set("forge.path", str(path), save=False)
        elif self.download.isChecked():
            self.cfg.set("sd.install_pending", self.install_dir.text().strip(), save=False)     # the main window downloads it
        return True


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
        for page in (LanguagePage(cfg), library_page, RatingPage(cfg), SystemPage(cfg, library_page), ForgePage(cfg, library_page), DonePage()):
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
        self.cfg.set("tutorial.pending", True, save=False)          # the main window shows the tutorial once
        self.cfg.save()
        super().accept()
