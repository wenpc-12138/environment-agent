# 全局行为规范(生态Agent 工作区)

本项目为生态环境领域智能体工作台。所有任务遵循以下规范:

1. 术语与口径:涉及污染物指标(如 SO2、NOx、PM2.5、COD、氨氮)必须附带单位与标准来源。
2. 引用标准:优先引用现行有效的国家标准(GB)、生态环境部标准(HJ)、行业标准与地方标准;标准编号须准确,不确定时标注"待核实"。
3. 知识库纪律:
   - 回答专业问题前必须先 kb_lookup 查本地知识库;
   - 落库前用 locate 按标准编号/标题/URL 精确定位, 已存在则复用原条目, 避免重复落库;
   - 本地无匹配时再 web_search 联网补充;
   - 有价值资料一律 kb_save 落库(五分类:网络资料/政府发布/标准规范/政策法规/其他),禁止随手丢弃;
   - 落库时尽量补充元数据: source_type(原文/官方解读/AI 分析/用户经验)、validity(现行/被替代/废止)、标准条目带 std_no/org/publish_date/implement_date;
   - 发现条目错误或过时时用 kb_correct 登记纠错(可附修正内容,条目自动降置信度待复核), 不用 delete 直接删;
   - 需要向用户汇报知识库规模/构成时用 kb_stats; 标准间引用/替代关系用 kb_relation 建立。
   - 语义相近但关键词不同的查询优先 kb_hybrid 多路召回(全文+向量+关系, RRF 融合);
   - 本地文档资料(PDF/DOCX/HTML/TXT/MD/XLSX)批量入库用 kb_import(自动解析/分类/分块向量化);
   - 定期 kb_audit 健康审计(完整性/置信度/纠错积压/冲突/重复), 发现冲突用 kb_relation 建立替代关系或 kb_correct 纠错;
   - 有价值问答对与用户偏好用 kb_harvest 收割沉淀(知识条目+记忆表);
   - 知识库备份/迁移用 kb_export(按领域导出 json/markdown zip)。
4. 任务记忆:用户明确交代的项目事实(项目名称、点位名称、委托方、时间节点)用 memory_set 持久化;对话中沉淀的用户偏好/事实由 kb_harvest 写入记忆表, 后续任务可 kb_memory 复用。
5. 输出规范:默认简体中文;结论在前,依据在后;可用表格、编号列表组织;禁止编造数据。

## 目录约定
- data/kb:本地知识库(FTS5 全文检索)
- data/agents/skills:特化技能(每个子目录一个 SKILL.md)
- data/agents/memory:任务记忆(存于 SQLite memory_entries)
