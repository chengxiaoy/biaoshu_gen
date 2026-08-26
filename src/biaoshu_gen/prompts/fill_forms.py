"""投标函+报价文件+货物一览表+资格证明文件填写 prompt（非 harness）。

LLM 直出填写 plan（FillOp 列表），python 经 fill_skill.run_fill_plan 执行；
执行报错回炉修正，表单格式原语全部确定性。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板的既有格式逐项生成填写操作。"

TEMPLATE = """任务：为响应模板副本生成填写操作序列（结构化输出 plan），系统将用确定性
原语逐条执行并产出 {output}。plan 每条操作的取值：
- {{"op":"blank","prefix":"项目名称：","value":"…"}}                    # 下划线填空（值在线上）
- {{"op":"cell","table_header":["序号","服务期"],"row":1,"col":1,"value":"…"}}  # 按表头定位填格
- {{"op":"replace","prefix":"致：","old":"（采购人名称）","new":"…"}}     # 段内文本替换
- {{"op":"picture","prefix":"备注：","img":"<预注入的图片绝对路径>","width":4.8,"caption":"附：营业执照"}}  # 实际插图
- {{"op":"append","prefix":"投标人名称：","value":"…"}}                  # 无填空线的段末追加

投标人企业资料（必填项，一律取自预注入的 facts）：
- 企业/投标人名称：{company_name}
- 法定代表人：{legal_person}
- 统一社会信用代码：{credit_code}

填写规则：
- 投标函：按模板格式填写，含项目名称/编号/投标有效期
- 报价数字（报价文件/开标一览表/分项报价表的金额单元格）一律写「〔待人工填写〕」
- 货物一览表：按预注入的采购清单与 metadata 逐项填入对应表格
- 资格证明文件：按模板小节填入企业资料与 kb 摘要资质，并实际插入相应图片（picture op，禁止读取图片内容）
- 企业资料若为 mock 占位值（含「待替换」），照填并在 plan 后无从标注--保持原值即可
- 只操作模板既有段落/表格（prefix 与 table_header 取自预注入的模板可填点地图），不新建结构
- 格式保持：不得删除/隐藏模板中的下划线、表格线、签字/盖章占位
- 若上次 plan 执行报错，只修正报错条目，输出修正后的完整 plan
"""


def build_user_prompt(output: str, company_name: str = "", legal_person: str = "",
                      credit_code: str = "") -> str:
    # 用 replace 而非 format：正文含 PLAN 字典花括号，format 会误解析
    return (TEMPLATE
            .replace("{output}", output)
            .replace("{company_name}", company_name or "（facts 缺失）")
            .replace("{legal_person}", legal_person or "（facts 缺失）")
            .replace("{credit_code}", credit_code or "（facts 缺失）"))
