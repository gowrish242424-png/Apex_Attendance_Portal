from datetime import datetime, timezone
from app.extensions import db

class SystemSetting(db.Model):
    """Stores system-wide configuration parameters."""
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    setting_key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<SystemSetting {self.setting_key}={self.setting_value}>"

    @classmethod
    def get_value(cls, key, default=None):
        """Retrieve setting value by key, returning default if not found."""
        setting = cls.query.filter_by(setting_key=key).first()
        return setting.setting_value if setting else default

    @classmethod
    def get_int(cls, key, default=0):
        """Retrieve setting value parsed as integer."""
        val = cls.get_value(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    @classmethod
    def set_value(cls, key, value, description=None):
        """Create or update a system setting."""
        setting = cls.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = str(value)
            if description is not None:
                setting.description = description
        else:
            setting = cls(
                setting_key=key,
                setting_value=str(value),
                description=description
            )
            db.session.add(setting)
        db.session.commit()
        return setting
