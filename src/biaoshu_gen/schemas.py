"""各 LLM 节点的输出模型（PydanticAI output_type）与 YAML 落盘工具。"""
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

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


class SectionBody(BaseModel):
    title: str
    content: str                 # Markdown 正文


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
    """偏离表数据行(序号由代码生成,模型不数数)。"""
    clause: str = ""          # 磋商文件章节条款号
    requirement: str = ""     # 磋商文件要求(摘原文)
    response: str = ""        # 响应文件的应答
    deviation: str = "无偏离"   # 偏离说明

    @field_validator("deviation")
    @classmethod
    def _blank_means_none(cls, v: str) -> str:
        return v if v.strip() else "无偏离"


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
    """LLM 直出的模板拆分归属(spans 之外的块归 commercial)。"""
    spans: list[SplitSpan] = Field(default_factory=list)


class FillOp(BaseModel):
    """fill_forms 的单个填写操作,字段语义与 fill_skill.run_fill_plan 的 plan 条目一致。"""
    op: str                            # blank / label / replace / cell / picture / append
    prefix: str = ""                   # 锚定段落前缀
    label: str = ""                    # label op:标签(段中部亦可,填全部命中)
    table_header: list[str] = Field(default_factory=list)   # cell 按表头定位(优先)
    table: int | None = None           # cell 按下标定位(无表头时)
    row: int = 0
    col: int = 0
    value: str = ""
    old: str = ""                      # replace 原文
    new: str = ""                      # replace 新文
    img: str = ""                      # picture 图片绝对路径
    width: float = 0.0                 # picture 宽(英寸)
    caption: str = ""                  # picture 图注


class FormsFill(BaseModel):
    """LLM 直出的 forms 填写 plan,由 python 执行 run_fill_plan 落盘。"""
    plan: list[FillOp] = Field(default_factory=list)


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
