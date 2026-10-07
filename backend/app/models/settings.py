import json

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPk
from app.models.base import utcnow_iso

DEFAULT_LLM = {"base_url": "", "api_key": "", "model": ""}
DEFAULT_HL_COLORS = {"yellow": "#fde68a", "green": "#bbf7d0", "blue": "#bfdbfe", "pink": "#fbcfe8"}
DEFAULT_PREFERENCES = {
    "chapter_length": 3000,
    "exercises_per_kp": 3,
    "highlight_colors": DEFAULT_HL_COLORS,
    "adhd_mode": "off",
    "course_font_size": 16,
    "drill_font_size": 15,
}



class AppSetting(Base):
    """单行表，id 恒为 local。"""

    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="local")
    llm: Mapped[str] = mapped_column(Text, default=json.dumps(DEFAULT_LLM))
    preferences: Mapped[str] = mapped_column(Text, default=json.dumps(DEFAULT_PREFERENCES))
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow_iso)
