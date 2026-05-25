"""路由模块：将 server.py 的 API 路由拆分到独立 Blueprint。"""
from flask import Blueprint

# 创建 Blueprint 实例
analysis_bp = Blueprint('analysis', __name__)
monitoring_bp = Blueprint('monitoring', __name__)
system_bp = Blueprint('system', __name__)
push_bp = Blueprint('push', __name__)

# 导入路由定义（必须在 Blueprint 创建之后）
from routes import analysis, monitoring, system, push  # noqa: E402, F401
