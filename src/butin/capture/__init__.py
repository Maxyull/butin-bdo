"""Capture d'écran, reconnaissance de texte, et découpage des lignes.

Seule couche qui touche à l'écran, et seule couche qui connaît la langue du
client. Tout ce qui est en dessous (`tracking/`) reçoit des lignes déjà lues et
déjà reconnues, et ignore aussi bien les pixels que le français.

Le format des lignes du client français est relevé sur de vraies captures dans
`docs/journal-acquisition.md`. À lire avant de toucher à `lines.py`.
"""

from .lines import ChatLineFormat, LineParts, ParsedLine, parse_frame, parse_line, split_line
from .ocr import (
    DEFAULT_SCALE,
    OcrEngine,
    TextBox,
    TextLine,
    TextReader,
    boxes_from_result,
    group_boxes,
    preprocess,
    stretch_contrast,
    upscale,
)
from .screen import CaptureError, GrayImage, Region, ScreenCapture, bgra_to_gray

__all__ = [
    "DEFAULT_SCALE",
    "CaptureError",
    "ChatLineFormat",
    "GrayImage",
    "LineParts",
    "OcrEngine",
    "ParsedLine",
    "Region",
    "ScreenCapture",
    "TextBox",
    "TextLine",
    "TextReader",
    "bgra_to_gray",
    "boxes_from_result",
    "group_boxes",
    "parse_frame",
    "parse_line",
    "preprocess",
    "split_line",
    "stretch_contrast",
    "upscale",
]
