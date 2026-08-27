"""
Script to capture actual high-resolution UI screenshots of Real-Time Translator.
"""
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtCore import Qt, QTimer, QSize, QPoint
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QImage
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QVBoxLayout

from rtt.settings import AppSettings
from rtt.history import SessionManager, TranscriptSession, _transcripts_dir
from rtt.main_window import MainWindow
from rtt.transcript_ui import NewSessionDialog
from rtt.overlay import SubtitleOverlay, _DualSubtitleWidget, OverlayBridge
from rtt.theme import DARK, LIGHT, load_custom_fonts, get_theme

def prepare_sample_data(session_mgr: SessionManager) -> TranscriptSession:
    sess1 = session_mgr.create_session(name="AI Tech Keynote 2026")
    sess1.set_pinned(True)
    
    entries = [
        ("Welcome everyone to the annual AI and speech translation keynote.",
         "Chào mừng mọi người đến với phiên hội thảo thường niên về AI và dịch thuật giọng nói."),
        ("Today, we are introducing ultra low-latency real-time translation with zero delay.",
         "Hôm nay, chúng tôi xin giới thiệu giải pháp dịch thuật thời gian thực siêu tốc với độ trễ gần như bằng không."),
        ("The system captures loopback audio directly via WASAPI without any virtual cables.",
         "Hệ thống tự động thu âm thanh loopback trực tiếp qua WASAPI mà không cần cài đặt cáp âm thanh ảo."),
        ("With Moonshine and Faster-Whisper, speech-to-text latency is reduced to under 80 milliseconds.",
         "Với Moonshine và Faster-Whisper, độ trễ nhận dạng giọng nói được rút ngắn xuống dưới 80 mili-giây."),
        ("Local LLMs like Llama 3.2 and Qwen 2.5 provide context-aware, fluent translations 100% offline.",
         "Các mô hình LLM cục bộ như Llama 3.2 và Qwen 2.5 mang lại bản dịch trôi chảy, đúng ngữ cảnh hoàn toàn offline.")
    ]
    for src, tgt in entries:
        sess1.add_entry(src, tgt)
    sess1.save()
    
    sess2 = session_mgr.create_session(name="Sprint Planning & Architecture Sync")
    sess2.add_entry(
        "Let's review the audio ducking implementation for Piper TTS.",
        "Hãy cùng đánh giá cơ chế tự động giảm âm lượng (ducking) cho Piper TTS."
    )
    sess2.save()
    
    sess3 = session_mgr.create_session(name="Review Phim Oppenheimer (2023)")
    sess3.add_entry(
        "Theory will only take you so far.",
        "Lý thuyết chỉ có thể đưa bạn đi xa đến thế thôi."
    )
    sess3.save()

    return sess1

def capture():
    app = QApplication.instance() or QApplication(sys.argv)
    load_custom_fonts()

    output_dir = BASE_DIR / "docs" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = AppSettings()
    settings.data.ui.theme = "dark"
    session_mgr = SessionManager()
    main_session = prepare_sample_data(session_mgr)

    # 1. Capture MainWindow - Transcript / Lịch sử hội thoại (Dark Mode)
    win = MainWindow(settings=settings, session=main_session)
    win.resize(1180, 760)
    win.show()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    
    tp = win.transcript_panel
    tp.reload_sessions_list()
    tp.set_session(main_session)
    
    # Open right summary sidebar with sample AI summary
    tp.right_sidebar.show()
    tp.right_sidebar.setMaximumWidth(280)
    tp.right_sidebar.setMinimumWidth(280)
    tp._right_sidebar_expanded = True
    if hasattr(tp, "summary_container"):
        tp.summary_container.show()
        tp.summary_text_area.setPlainText(
            "Tóm tắt cuộc họp (Gemini AI):\n"
            "• Thảo luận ra mắt hệ thống dịch Real-Time Translator.\n"
            "• Tối ưu độ trễ STT Moonshine dưới 80ms.\n"
            "• Tích hợp Llama-3.2 & Qwen 2.5 offline cho dịch thuật ngữ cảnh tự nhiên.\n"
            "• Hỗ trợ thuyết minh cabin với Piper TTS và Auto-Ducking."
        )
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    
    pix1 = win.grab()
    pix1.save(str(output_dir / "01_ui_transcript_dark.png"), "PNG")
    print("Saved 01_ui_transcript_dark.png")

    # 2. Capture MainWindow - Cài đặt / Settings Tab (Model & Engines)
    win.set_tab(1)
    if hasattr(win.settings_panel, "_set_tab"):
        win.settings_panel._set_tab(1)
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    
    pix2 = win.grab()
    pix2.save(str(output_dir / "02_ui_settings_dark.png"), "PNG")
    print("Saved 02_ui_settings_dark.png")
    win.close()

    # 3. Capture NewSessionDialog
    dlg = NewSessionDialog(theme=DARK, default_name="Hội thảo Công nghệ AI & Trí Tuệ Nhân Tạo")
    dlg.show()
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()
    pix3 = dlg.grab()
    pix3.save(str(output_dir / "03_new_session_dialog.png"), "PNG")
    print("Saved 03_new_session_dialog.png")
    dlg.close()

    # 4. Capture Subtitle Overlay on dark background container
    overlay_box = QWidget()
    overlay_box.setFixedSize(900, 240)
    overlay_box.setStyleSheet("background-color: #0d1117;")
    box_layout = QVBoxLayout(overlay_box)
    box_layout.setContentsMargins(40, 30, 40, 30)
    
    subtitle_widget = _DualSubtitleWidget(
        main_pt=18,
        font_family="Be Vietnam Pro",
        show_original=True,
        bg_opacity=0.88,
        alignment="center",
        card_width=760,
        parent=overlay_box
    )
    subtitle_widget.set_committed_text("With Moonshine and Faster-Whisper, speech-to-text latency is reduced to under 80ms.")
    subtitle_widget.set_committed_text("Các mô hình LLM cục bộ mang lại bản dịch trôi chảy, đúng ngữ cảnh hoàn toàn offline.")
    box_layout.addWidget(subtitle_widget)
    
    overlay_box.show()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    pix4 = overlay_box.grab()
    pix4.save(str(output_dir / "04_subtitle_overlay.png"), "PNG")
    print("Saved 04_subtitle_overlay.png")
    overlay_box.close()

    # 5. Capture MainWindow in Light Mode
    settings_light = AppSettings()
    settings_light.data.ui.theme = "light"
    win_light = MainWindow(settings=settings_light, session=main_session)
    win_light.resize(1180, 760)
    win_light.show()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    win_light.transcript_panel.reload_sessions_list()
    win_light.transcript_panel.set_session(main_session)
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    pix5 = win_light.grab()
    pix5.save(str(output_dir / "05_ui_transcript_light.png"), "PNG")
    print("Saved 05_ui_transcript_light.png")
    win_light.close()

    print("SUCCESS: All screenshots captured from actual Qt code!")

if __name__ == "__main__":
    capture()
