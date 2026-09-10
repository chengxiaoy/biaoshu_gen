"""各 LLM 节点的输出模型（PydanticAI output_type）与 YAML 落盘工具。"""
from pathlib import Path
from typing import Annotated, Literal, TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, field_validator

T = TypeVar("T", bound=BaseModel)


class TenderMetadata(BaseModel):
    """标书元数据。"""
    project_name: str = ""
    project_no: str = ""
    background: str = ""
    bid_deadline: str = ""       # 投标截止/开标时间
    delivery_date: str = ""      # 交货日期要求
    warranty_period: str = ""    # 质保期要求
    other_commercial: list[str] = Field(default_factory=list)
    bid_type: Literal["服务", "货物", "工程", ""] = ""   # 标书类型（政府采购三分法）

    @field_validator("bid_type", mode="before")
    @classmethod
    def _norm_bid_type(cls, v):
        """LLM 输出归一：去空白；「货物类/建设工程/施工服务」等变体映射到三类
        （匹配序 工程>货物>服务——工程词最特异，「货物及服务」判货物）；
        未识别值留空（下游可按需人工补判）。"""
        if not isinstance(v, str):
            return ""
        v = v.strip()
        for t in ("工程", "货物", "服务"):
            if t in v:
                return t
        return ""


class TenderRequirements(BaseModel):
    """标书需求。"""
    purchase_list: list[str] = Field(default_factory=list)
    project_overview: str = ""
    tech_requirements: list[str] = Field(default_factory=list)
    implementation_requirements: list[str] = Field(default_factory=list)


class InvalidationItem(BaseModel):
    kind: str = Field(pattern="^(废标项|扣分项)$")
    requirement: str = ""
    source_quote: str = ""       # 招标文件原文依据


class InvalidationItems(BaseModel):
    items: list[InvalidationItem] = Field(default_factory=list)


class ScoringStandards(BaseModel):
    """评标标准。"""
    price_rules: str = ""
    commercial_rules: list[str] = Field(default_factory=list)
    technical_rules: list[str] = Field(default_factory=list)


class GlobalFacts(BaseModel):
    """全局事实设定（人工控制点 1：03_facts.yaml）。"""
    schedule: str = ""           # 工期设置
    staffing: str = ""           # 人员配置
    software_metrics: list[str] = Field(default_factory=list)
    goods_list: list[str] = Field(default_factory=list)   # 货物名列表（仅货物类标书：本次投标覆盖的产品名）
    extra: list[str] = Field(default_factory=list)
    # 投标人企业资料（表格填写用；缺失时由 ensure_business_fields mock 占位）
    company_name: str = ""       # 企业/投标人名称
    legal_person: str = ""       # 法定代表人
    credit_code: str = ""        # 统一社会信用代码
    # 响应模板中提炼的待填信息（facts 阶段预置：项目名称/编号/采购计划备案号/采购人等）
    template_fields: dict[str, str] = Field(default_factory=dict)


class OutlineNode(BaseModel):
    """三级提纲节点：一级章 / 二级节 / 三级小节。

    无 children 的节点即叶子（三级小节），叶子带 target_words 作为正文生成与字数校验单位。
    id 形如 "1"、"1.1"、"1.1.1"。
    """
    id: str = ""
    title: str
    description: str = ""                      # 写作要点（简短）
    target_words: int = 0                      # 仅叶子节点使用
    children: list["OutlineNode"] = Field(default_factory=list)
    media_type: Literal["table", "figure"] | None = None # 仅叶子节点使用
    media_score: float = 0.0                             # 图表需求强度 0~1（全局限额排序用）

    def leaves(self) -> list["OutlineNode"]:
        if not self.children:
            return [self]
        return [leaf for c in self.children for leaf in c.leaves()]


class Outline(BaseModel):
    """技术方案目录（人工控制点 2：04_outline.yaml）。sections 必填且至少一章。

    注意：不能用 default_factory——pydantic v2 默认不校验默认值，
    模型省略该字段时会静默得到空列表（实测踩坑）。
    """
    sections: list[OutlineNode] = Field(min_length=1)
    total_words: int = 0

    def leaves(self) -> list[OutlineNode]:
        return [leaf for s in self.sections for leaf in s.leaves()]


class CompactOutlineNode(BaseModel):
    """outline 紧凑输出节点：单字母键（t/d/w/c）专为 LLM 生成省 token——

    相比全名键的递归 JSON，每个节点省 ~15-20 输出 token（65 节点省千级）。
    id 与 total_words 不让模型生成：由 to_node/to_outline 按树位置推导。
    """

    t: str = Field(description="标题，不超过25个汉字，不含写作建议或括号说明")
    d: str = Field(default="", description="写作要点一句话，不超过60个汉字")
    w: int = Field(default=0, description="预期字数；仅三级小节给出，其余节点为0")
    c: list["CompactOutlineNode"] = Field(default_factory=list, description="子节点")

    def to_node(self, path: str) -> "OutlineNode":
        """位置编号映射回 OutlineNode：path 即 id（"1"、"1.1"、"1.1.1"）。"""
        children = [c.to_node(f"{path}.{i}") for i, c in enumerate(self.c, 1)]
        return OutlineNode(
            id=path,
            title=self.t.strip(),
            description=self.d.strip(),
            # 非叶节点的 w 无意义（总字数按叶子求和），置 0 与既有口径一致
            target_words=self.w if not self.c else 0,
            children=children,
        )


class CompactOutline(BaseModel):
    """outline 阶段的 LLM 输出模型（CompactOutlineNode 的嵌套容器）。"""

    s: list[CompactOutlineNode] = Field(min_length=1, description="一级章列表")

    def to_outline(self) -> "Outline":
        sections = [s.to_node(str(i)) for i, s in enumerate(self.s, 1)]
        outline = Outline(sections=sections)
        # total_words 以叶子之和为准（不信模型自报，与 outline 节点既有口径一致）
        return outline.model_copy(
            update={"total_words": sum(l.target_words for l in outline.leaves())})


class SectionBody(BaseModel):
    title: str
    content: str                 # Markdown 正文

class SectionMedia(BaseModel):
    type: Literal["table", "figure"] | None = None
    media_content: str = ""   ## mermaid文本 或者是 table的markdown文本
    media_caption: str = ""   ## table caption 或者是 figure caption


class MediaNeedItem(BaseModel):
    """二级单元媒体需求判定的一条（rich_body_v2：按二级交互、三级格式返回）。"""
    sec_id: str = ""                        # 对应三级小节 id（"1.1.1"）
    type: Literal["table", "figure", "none"] = "none"
    score: float = 0.0


class UnitMediaNeeds(BaseModel):
    """一个二级节的媒体需求集合（一次 LLM 调用覆盖该节全部三级小节）。"""
    needs: list[MediaNeedItem] = Field(default_factory=list)


class UnitSectionBody(BaseModel):
    """二级单元正文返回的一条（三级小节粒度，sec_id 对位）。"""
    sec_id: str = ""
    title: str = ""
    content: str = ""


class UnitBodies(BaseModel):
    """一个二级节的全部三级小节正文（一次 LLM 调用返回）。"""
    sections: list[UnitSectionBody] = Field(default_factory=list)


class MediaNeed(BaseModel):
    """图表需求判定（rich_body 预置阶段输出）。"""
    type: Literal["table", "figure", "none"] = "none"
    score: float = 0.0        # 需求强度 0~1，全局限额时按此排序保留


class InsertPoint(BaseModel):
    """媒体插入位置：插入到第 index 段之前（段落从 0 编号）。"""
    index: int = Field(
        default=0,
        description="插入到第 index 个段落之前,取 0..正文段数;-1=正文已有类似图表,跳过插入")

class BodyReviewReport(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    problem_sections: list[str] = Field(default_factory=list)   # 有问题的三级小节 id 列表


class AspectReview(BaseModel):
    """review 单项（废标扣分/事实一致性/引用/材料/格式/模板结构）审核结论。"""
    name: str
    passed: bool
    note: str = ""


class StructureHeading(BaseModel):
    """无标题样式文档重建出的单个章节边界(块序号定界)。"""
    index: int
    level: int
    title: str


class StructureOutline(BaseModel):
    """LLM 结构重建输出:按文档块序排列的章节标题列表。"""
    headings: list[StructureHeading] = Field(default_factory=list)


class TemplateAnchor(BaseModel):
    """LLM 定位的响应文件格式章节边界(块序号)。end_index=None 表示到文档末尾。"""
    start_index: int
    end_index: int | None = None


class DeviationRow(BaseModel):
    """偏离表数据行(序号由代码生成,模型不数数)。

    description 进 JSON schema 被 LLM 直接看到(prompt 规则就近带到字段);
    requirement/response 必填挡漏字段,空白串仍由节点层 _validate(strip 语义)拦截。
    """
    clause: str = Field(default="", description="磋商/招标文件的章节条款号;要求无条款号时可空")
    requirement: str = Field(description="招标要求:摘录原文要点,禁止为空")
    response: str = Field(description="响应文件的应答:逐条明确应答,应满足招标要求各项参数，将要求中的参数范围更改为明确最低符合要求的标准值（上界或者下界）")
    deviation: str = Field(default="无偏离", description="偏离说明:无偏离/正偏离(优于要求)，尽量无偏离")

    @field_validator("deviation")
    @classmethod
    def _blank_means_none(cls, v: str) -> str:
        return v.strip() or "无偏离"


class DeviationTableRows(BaseModel):
    """单张偏离表的填写结果;table_index 对应 prompt 中标注的表序号(1 起)。"""
    table_index: int
    rows: list[DeviationRow] = Field(default_factory=list)


class DeviationTables(BaseModel):
    """LLM 直出的偏离表填写结果:按模板中实际发现的表动态,不写死类别。"""
    tables: list[DeviationTableRows] = Field(default_factory=list)


class SplitSpan(BaseModel):
    """无标题模板 LLM 兜底的块区间归属。end_index=None 表示到文档末尾。"""
    start_index: int
    end_index: int | None = None
    bucket: str


class TemplateSplit(BaseModel):
    """LLM 直出的模板拆分归属(spans 之外的块归 forms 其余整体)。"""
    spans: list[SplitSpan] = Field(default_factory=list)


# ---- fill plan 条目按 op 分型（discriminated union）----
# 12 字段扁模型实测全量空填(真实 run 输出 58% 是空字段,"label":""/"table":null/"row":0…)，
# 模型顺着 JSON schema property 逐个生成。分型后模型按选中分支只填本 op 的 3-6 个字段，
# 输出 token 直降——decoding 是 plan 生成耗时的最大头。
class LabelOp(BaseModel):
    """label=按填写位置的前缀词组填空（最常用的 op）。"""
    op: Literal["label"] = Field(
        description="label=按填写位置的前缀词组填空:label 填模板地图中该位置的开头前缀词组"
                    "(照抄到「标签+冒号」为止,勿带 tab/空格/旧值),前缀可在段首或段中,填全部命中;"
                    "值落前缀后的下划线空位(无下划线则直接跟在后面),前缀后已是实义文本(已填过)"
                    "的自动跳过")
    label: str = Field(
        description="填写位置的前缀词组:从模板可填点地图照抄该位置的起始文本,一字不差"
                    "(到「标签+冒号」为止,勿带 tab/空格/旧值,括号宽度与模板一致);前缀可在段首"
                    "或段中(如「编号：__ 名称：__」同段多空),填全部命中的空位")
    value: str = Field(description="填写值")


class ReplaceOp(BaseModel):
    """replace=段内文本替换（「（项目名称）」等括号占位文体）。"""
    op: Literal["replace"] = Field(
        description="replace=段内文本替换:「（项目名称）」「（采购人名称）」等括号占位整体换实际值")
    prefix: str = Field(
        description="replace/picture/append 的段落锚:段落须以它开头(抄模板可填点地图中"
                    "该段的开头文本,到「标签+冒号」为止,勿带 tab/空格/旧值);只命中第一个匹配段落")
    old: str = Field(description="被替换原文(照抄模板原文;全半角括号宽度已自动归一化)")
    new: str = Field(description="替换文本")


class CellOp(BaseModel):
    """cell=填单个表格单元格（table_header 或 table 二选一定位）。"""
    op: Literal["cell"] = Field(description="cell=填单个表格单元格(同表多格优先用 table 按行批量填)")
    table_header: list[str] = Field(
        default_factory=list,
        description="cell 按表头定位(优先用):表头行须含全部关键词,照抄地图 [Tk] 后的表头文本")
    table: int | None = Field(
        default=None,
        description="cell 按表格下标定位(表头无关键词时):填地图 [Tk] 中的 k")
    row: int = Field(default=0, description="cell 的行号,从 0 起(0=表头行,数据行自 1 起);超出现有行数自动加行")
    col: int = Field(default=0, description="cell 的列号,从 0 起")
    value: str = Field(description="填写值")


class TableOp(BaseModel):
    """table=按行批量填表格（同表多格合并为一条，省逐格 cell 的 table_header 重复）。

    实测:106 条逐格 cell 的 plan 输出 30KB、表头抄 100+ 遍;rows 二维化后省 ~64%。
    """
    op: Literal["table"] = Field(
        description="table=按行批量填表:rows 每个内层 list 是一行,自 start_row 起逐行;"
                    "格值 null 或空串=跳过该格(保留原样);行数不足自动加行。同表多格优先用它,"
                    "散落个别格子才用 cell")
    table_header: list[str] = Field(
        default_factory=list,
        description="按表头定位(优先用):表头行须含全部关键词,照抄地图 [Tk] 后的表头文本")
    table: int | None = Field(
        default=None,
        description="按表格下标定位(表头无关键词时):填地图 [Tk] 中的 k")
    start_row: int = Field(default=1, description="首个数据行行号(默认 1=表头后第一行)")
    rows: list[list[str | None]] = Field(
        description="数据行二维数组,按列顺序对位;null=跳过该格")


class AppendOp(BaseModel):
    """append=段落末尾追加（找不到标签锚时才补内容）。"""
    op: Literal["append"] = Field(description="append=段落末尾追加:找不到标签锚时才补内容")
    prefix: str = Field(description="锚段落前缀(段落须以它开头,照抄地图)")
    value: str = Field(description="追加文本")


# discriminator=op:模型按 op 值选中分支,输出只含该分支字段
# picture 不在 plan op 之列(feedback #86 终版):插图位置由 harness agent 对照文档实况
# 自主决定,程序化 plan 只管文字/表格填写
FillOp = Annotated[
    LabelOp | ReplaceOp | CellOp | TableOp | AppendOp,
    Field(discriminator="op"),
]


class FormsFill(BaseModel):
    """LLM 直出的 forms 填写 plan,由 python 执行 run_fill_plan 落盘。"""
    plan: list[FillOp] = Field(
        default_factory=list,
        description="填写操作序列;op 选型:label=按标签填空(最常用) / replace=括号占位替换"
                    "(全部命中) / table=同表多格按行批量填(优先) / cell=散落单格 / "
                    "append=段末追加(找不到标签锚时才用);每条只填本 op 的字段;"
                    "**不发 picture**(插图由后续 harness 阶段自主处理);"
                    "**金额等人工填写项与缺失资料不发 op**(〔待人工填写〕/〔待补〕等占位值"
                    "会被系统丢弃),空位保持原样留给人工")


class ReviewReport(BaseModel):
    """review 节点结构化输出（PydanticAI 单次调用）。

    issues 仅收可修复草稿缺陷；数据缺失类（证件/联系方式/证明材料等需人工补全）
    归 human_todos，不计入结论。
    """
    passed: bool
    aspects: list[AspectReview] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    human_todos: list[str] = Field(default_factory=list)


def to_yaml_file(model: BaseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(model.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def from_yaml_file(cls: type[T], path: Path) -> T:
    """读取并校验；失败抛 ValueError（字段级信息），不静默吞掉用户编辑错误。"""
    try:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as e:
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(f"{path} 校验失败: {detail}") from e
