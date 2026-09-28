"""
模型统一导出
"""

from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.chat_history import ChatHistory
from app.models.retrieval_log import RetrievalLog

__all__ = ["User", "KnowledgeBase", "Document", "Chunk", "ChatHistory", "RetrievalLog"]
"""
============================================================
📌 Day 10 踩坑记录（2026-08-17）
============================================================

【问题 1】模型文件创建顺序混乱
现象：先建了 document.py 和 chunk.py，但 user.py 和 knowledge_base.py 还没建。
原因：没有按“依赖顺序”创建模型文件。
教训：四张表有层级依赖（User → KnowledgeBase → Document → Chunk），
      应该从顶层开始建：先 user.py，再 knowledge_base.py，再 document.py，再 chunk.py。
      如果顺序乱了，测试时会出现 ImportError 或外键引用失败。

【问题 2】表名 `__tablename__` 容易写成复数
现象：建表后查询时报错 `no such table: user`。
原因：表名写成了 `__tablename__ = "user"`（单数），但 SQL 查询时写的是 `users`。
教训：SQLAlchemy 官方推荐表名用**复数**（users、documents、chunks），
      查询时也必须用同样的名字。统一命名规则，避免混淆。

【问题 3】`relationship` 写在子表里，反向属性自动生成
现象：在 User 表里找不到 `relationship`，但 `user.knowledge_bases` 却能正常使用。
原因：`KnowledgeBase` 表里写了 `user = relationship("User", backref="knowledge_bases")`，
      这个 `backref` 会自动在 User 上生成 `knowledge_bases` 属性。
教训：关联关系只需要在子表里定义一次，不需要在父表里重复写。

【问题 4】测试数据必须手动插入才能验证表是否正常
现象：建表后没有数据，`db.query(User).first()` 返回 None。
原因：`Base.metadata.create_all()` 只建表，不插入任何数据。
教训：测试时需要用 `db.add()` + `db.commit()` 插入至少一条数据，才能验证表结构和关联关系是否正常。

【问题 5】`from app.models import *` 不会自动导入所有模型
现象：在 `test_db.py` 里用 `from app.models import *` 后，`User` 仍然未定义。
原因：`__all__` 没有在 `__init__.py` 中正确配置。
教训：在 `app/models/__init__.py` 中明确写出 `__all__ = ["User", "KnowledgeBase", "Document", "Chunk", "ChatHistory"]`，
      才能通过 `from app.models import *` 一次性导入所有模型。

【问题 6】`__repr__` 对数据库没影响，但调试很有用
现象：打印 `user` 时显示 `<app.models.user.User object at 0x...>`，看不出内容。
原因：没有定义 `__repr__` 方法。
教训：建议每个模型都加上 `__repr__`，方便在终端看到直观的数据，调试效率更高。

【问题 7】`engine` 和 `SessionLocal` 的区别
现象：搞不清 `engine` 和 `SessionLocal` 分别是什么。
原因：它们虽然都出现在 `database.py` 里，但职责不同。
教训：
  - `engine`：负责连接数据库（管道）
  - `SessionLocal`：负责创建会话（办事窗口）
  - `Base`：负责登记模型（户口本）
  三者在建表和操作数据时各自发挥作用，各司其职。

【问题 8】字段长度不够导致数据插入失败
现象：`String(20)` 存 `"application/pdf"` 时报错。
原因：`application/pdf` 长度为 18，但加上其他可能的 MIME 类型（如 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`）可能超过 20。
教训：对于可能变长的字段（如 `file_type`），预估最大值并适当放大长度（如 `String(50)`）。
"""