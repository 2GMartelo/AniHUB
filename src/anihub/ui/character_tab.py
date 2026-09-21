"""The "Standard character" tab: the character every picture of the prompt builder's tags is drawn on (her hair, eyes, clothes, the negative
prompt, seed, size, model...). Saved once, it is what "draw this picture" and "draw all the pictures" use."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import promptbook as pb
from anihub.services.tagpictures import PictureMaker
from anihub.ui import style
from anihub.ui.workers import run_async

SAMPLE_TAG = {"slot": "expression", "text": "smile", "id": 1}          # the test picture: her face with a smile
SAMPLE_CATEGORY = "expression.mood"
PICTURE = 300


class CharacterTab(QWidget):
    """`hooks`: `api() -> ForgeApi | None` (a running Forge), `start()` starts Forge, `regenerate()` redraws every tag picture."""

    def __init__(self, ctx: AppContext, hooks: dict | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.hooks = ctx, hooks or {}
        self._drawing = False
        ch = pb.character_from(ctx.cfg.get("promptbook.character"))

        self.hair = QLineEdit(ch["hair"])
        self.eyes = QLineEdit(ch["eyes"])
        self.top = QLineEdit(ch["top"])
        self.bottom = QLineEdit(ch["bottom"])
        self.shorts = QLineEdit(ch["shorts"])
        self.extra = QLineEdit(ch["extra"], placeholderText="glasses, ahoge …")
        self.negative = QLineEdit(ch["negative"], placeholderText=tr("char.negative_hint"))
        self.model = QComboBox(editable=True)
        self.model.setEditText(ch["model"])
        self.model.lineEdit().setPlaceholderText(tr("char.model_hint"))
        self.seed = QSpinBox(minimum=-1, maximum=2147483647, value=int(ch["seed"]))
        self.size = QSpinBox(minimum=256, maximum=2048, singleStep=64, value=int(ch["size"]))
        self.steps = QSpinBox(minimum=4, maximum=100, value=int(ch["steps"]))
        self.cfg = QDoubleSpinBox(minimum=1, maximum=20, singleStep=0.5, decimals=1, value=float(ch["cfg"]))
        self.sampler = QLineEdit(ch["sampler"])

        for name, widget, hint in (("hair", self.hair, "char.hair_hint"), ("eyes", self.eyes, ""), ("top", self.top, "char.top_hint"),
                                   ("bottom", self.bottom, "char.bottom_hint"), ("shorts", self.shorts, "char.shorts_hint")):
            widget.setToolTip(tr(hint) if hint else "")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(9)
        form.addRow(tr("char.hair"), self.hair)
        form.addRow(tr("char.eyes"), self.eyes)
        form.addRow(tr("char.top"), self.top)
        form.addRow(tr("char.bottom"), self.bottom)
        form.addRow(tr("char.shorts"), self.shorts)
        form.addRow(tr("char.extra"), self.extra)
        form.addRow(tr("char.negative"), self.negative)
        form.addRow(tr("sd.model"), self.model)
        form.addRow(tr("sd.seed"), self.seed)
        form.addRow(tr("sd.size"), self.size)
        form.addRow(tr("sd.steps"), self.steps)
        form.addRow("CFG", self.cfg)
        form.addRow(tr("sd.sampler"), self.sampler)

        intro = style.role(QLabel(tr("char.intro")), "dim")
        intro.setWordWrap(True)
        self.save_btn = style.primary(QPushButton(tr("lora.save")), "check")
        self.reset_btn = style.secondary(QPushButton(tr("char.reset")), "rotate")
        self.test_btn = style.secondary(QPushButton(tr("char.test")), "image")
        self.all_btn = style.secondary(QPushButton(tr("pb.regen_all")), "refresh")
        self.message = style.role(QLabel(), "dim")
        self.message.setWordWrap(True)
        buttons = QHBoxLayout()
        for b in (self.save_btn, self.reset_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(intro)
        ll.addLayout(form)
        ll.addLayout(buttons)
        ll.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        scroll.setMinimumWidth(430)

        self.picture = QLabel(tr("char.no_picture"), alignment=Qt.AlignmentFlag.AlignCenter)
        self.picture.setObjectName("thumbHolder")
        self.picture.setFixedSize(PICTURE, PICTURE)
        self.picture.setWordWrap(True)
        self.sample = QPlainTextEdit(readOnly=True)
        self.sample.setMaximumHeight(150)
        right = QVBoxLayout()
        right.addWidget(style.role(QLabel(tr("char.preview")), "h2"))
        right.addWidget(self.picture, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.test_btn, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(QLabel(tr("char.sample")))
        right.addWidget(self.sample)
        right.addSpacing(8)
        right.addWidget(self.all_btn, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.message)
        right.addStretch(1)
        layout = QHBoxLayout(self)
        layout.addWidget(scroll, 3)
        layout.addLayout(right, 2)

        self.save_btn.clicked.connect(self.save)
        self.reset_btn.clicked.connect(self._reset)
        self.test_btn.clicked.connect(self.test)
        self.all_btn.clicked.connect(self._regenerate)
        for edit in (self.hair, self.eyes, self.top, self.bottom, self.shorts, self.extra, self.negative):
            edit.textChanged.connect(self._update_sample)
        self._update_sample()

    # --- the settings ------------------------------------------------------------------------------------------------

    def values(self) -> dict:
        return {"hair": self.hair.text(), "eyes": self.eyes.text(), "top": self.top.text(), "bottom": self.bottom.text(),
                "shorts": self.shorts.text(), "extra": self.extra.text(), "negative": self.negative.text(),
                "model": self.model.currentText(), "seed": self.seed.value(), "size": self.size.value(), "steps": self.steps.value(),
                "cfg": self.cfg.value(), "sampler": self.sampler.text()}

    def save(self) -> None:
        self.ctx.cfg.set("promptbook.character", pb.character_from(self.values()))
        self.message.setText(tr("lora.saved"))

    def _reset(self) -> None:
        d = pb.DEFAULT_CHARACTER
        for widget, key in ((self.hair, "hair"), (self.eyes, "eyes"), (self.top, "top"), (self.bottom, "bottom"), (self.shorts, "shorts"),
                            (self.extra, "extra"), (self.negative, "negative"), (self.sampler, "sampler")):
            widget.setText(d[key])
        self.model.setEditText(d["model"])
        self.seed.setValue(d["seed"])
        self.size.setValue(d["size"])
        self.steps.setValue(d["steps"])
        self.cfg.setValue(d["cfg"])

    def _update_sample(self) -> None:
        prompt, negative = pb.preview_prompt("clothing", "school uniform", "clothing.outfit", pb.character_from(self.values()))
        self.sample.setPlainText(prompt + "\n\n" + tr("sd.negative") + ": " + negative)

    def set_models(self, titles: list[str]) -> None:
        """The checkpoints Forge has (filled in when Forge is running); what was typed stays."""
        current = self.model.currentText()
        self.model.clear()
        self.model.addItems(titles)
        self.model.setEditText(current)

    # --- drawing -------------------------------------------------------------------------------------------------------------

    def test(self) -> None:
        """Draws the sample picture with the settings as they are now (saved or not) to see the character before drawing everything."""
        api = self.hooks["api"]() if self.hooks.get("api") else None
        if api is None:
            if self.hooks.get("start") and QMessageBox.question(self, tr("pb.start_forge_title"), tr("pb.start_forge")) == QMessageBox.StandardButton.Yes:
                self.hooks["start"]()
                self.message.setText(tr("pb.forge_starting"))
            else:
                self.message.setText(tr("pb.need_forge"))
            return
        if self._drawing:
            return
        self._drawing = True
        self.test_btn.setEnabled(False)
        self.message.setText(tr("pb.previews.working", n=1))
        maker = PictureMaker(api, self.values())

        def done(data: bytes) -> None:
            self._drawing = False
            self.test_btn.setEnabled(True)
            pm = QPixmap()
            pm.loadFromData(data)
            self.picture.setPixmap(pm.scaled(PICTURE, PICTURE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.message.setText(tr("char.tested"))

        def failed(exc: Exception) -> None:
            self._drawing = False
            self.test_btn.setEnabled(True)
            self.message.setText(tr("status.error", msg=str(exc)))

        run_async(lambda: maker.draw(SAMPLE_TAG, SAMPLE_CATEGORY), on_done=done, on_error=failed)

    def _regenerate(self) -> None:
        self.save()                                         # the pictures are drawn on what is written here
        if self.hooks.get("regenerate"):
            self.hooks["regenerate"]()
