"""各 LLM 节点的输出模型（PydanticAI output_type）与 YAML 落盘工具。"""
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError

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


class ParseResult(BaseModel):
    """parse_tender 节点的聚合输出。"""
    metadata: TenderMetadata
    requirements: TenderRequirements
    invalidation: InvalidationItems
    scoring: ScoringStandards


class TocAssignment(BaseModel):
    """章节分类结果：一个章节可同时属于多组。"""
    index: int                      # 章节序号（1 起，与 docx_to_sections 顺序一致）
    title: str
    categories: list[str] = Field(default_factory=list)   # metadata/requirements/invalidation/scoring 子集，可为空


class TocMap(BaseModel):
    assignments: list[TocAssignment] = Field(default_factory=list)


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
