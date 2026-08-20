- [x] 当前生成 技术方案的outline和正文 质量不佳，有以下改进点可以提高：
  1. 生成技术方案的outline 的 prompt中不用参考  template_md, template中不会有关于 技术方案 响应文件的格式要求
  2. 生成的outline 可以 细分到三级提纲 可以参考以下要求

`你是一个专业的标书编写专家。根据提供的项目概述和技术评分要求，生成投标文件中技术标部分的目录结构。

要求：
1. 目录结构要全面覆盖技术标的所有必要章节
2. 章节名称要专业、准确，符合投标文件规范
3. 一级目录名称要与技术评分要求中的章节名称一致，如果技术评分要求中没有章节名称，则结合技术评分要求中的内容，生成一级目录名称
4. 一共包括三级目录
5. 返回标准JSON格式，包含章节编号、标题、描述和子章节
6. 除了JSON结果外，不要输出任何其他内容

JSON格式要求：
{
  "outline": [
    {
      "id": "1",
      "title": "",
      "description": "",
      "children": [
        {
          "id": "1.1",
          "title": "",
          "description": "",
          "children":[
              {
                "id": "1.1.1",
                "title": "",
                "description": ""
              }
          ]
        }
      ]
    }
  ]
}`
  
  3. 正文生成时可以并发执行，传入提纲上下文，同时可以控制并发数量，暂定为2
  4. 在正文review后回退到正文修改时，不用做总体的修复，只需要修复有问题的三级章节

- [x] 在填写偏离表节点时，应遵循以下要求
  1. 应该严格按照招标文件的响应模板中的偏离表格式进行填写，而不是生成偏离表后再插入文档
  2. 如果招标文件中没有偏离表部分，则跳过该节点，无需填写

- [x] 在编写商务响应文件时，该文件也应该严格遵循响应文件模板格式，而不是生成后再插入，应在原有模板副本中插入相应信息文字或图片
- [x] 关于当前命令行执行时无法从已经生成的阶段再次生成的问题，可以考虑在每个阶段都备份当前阶段完成时的checkpoint以支持可以选择性重跑
- [x] 在填写表格时，需要的必要的 法人名 投标名 企业名 企业信用代码 等资料，应该从facts.yaml中获取，当发现facts.yaml中缺少信息时，mock相应的名称或代码放到facts.yaml 文件中
- [x] 在最终节点review时应确保 技术方案正文的标题格式应该和响应模板中整体的标题结构融合，同时不能删减或调整当前响应模板文件中的结构或章节
- [x] KnowledgeBase 该类也应该支持解析PDF文件 可以考虑使用markitdown 将pdf转成markdown放到知识库中（markitdown 在 Py3.14 无 onnxruntime 轮子，改用 pypdf 文本提取；坏/扫描 PDF 跳过不拖垮加载）

- [x] 检查fill阶段的harness填写的策略，应该都从当前的标书模板副本中填写，而不是重新生成新的docx文档，这样可以尽量保证投标文档的格式和模板文档一致（fill_forms/deviation/commercial 三节点统一：以 标书模板.docx 为格式依据在模板副本中填写，无模板则跳过）
- [x] 在fill阶段时，如果有需要将图片插入到文档的情况，请插入图片，不要插入路径，这和不让大模型读取图片内容并不冲突，大模型可以依据图片文件名判断是否需要插入该图片（fill_forms/commercial/deviation 三 prompt 统一：add_picture 实际插入，仍禁止读取图片内容，依据文件名判断）
- [x] 在商务响应文件填充时，请依据事实填充，不要编造（commercial prompt：承诺与 facts 一致，资质/案例/人员/业绩只能引用 kb.md 实有内容，缺失留空或注〔待补〕）
- [x] 在进行填写表格类文件时，请勿删除下划线，同时保持原有格式（fill_forms/commercial/deviation：不得删除/隐藏下划线、表格线、签字/盖章占位，保持模板原格式）
- [x] 为harness节点中的 claude code agent 设置日志 extra_args={"debug-file": "/path/to/your/debug.log"}（harness._query_sdk 自动定位 run 目录并设置 debug-file 到 run/harness_debug.log） 
- [x] harness 节点的debug 日志路径不对，注意各harness节点的debug日志应该区分开，修复该问题，并阅读debug日志文件，分析各个harness节点执行慢效率不高的原因和问题（已按节点分文件 harness_debug/<工作区>.log；慢因分析：fill 阶段 80% 时间耗在 harness 逐段探查模板段落/run 下标与试错，实际填写是确定性 python-docx 操作——已用 fill_skill 前缀锚定原语消除探查）
- [x] 在抽取 facts 阶段，就应该阅读响应模板表格部分，提炼出需要的各类信息和名称或者编号，并预置在facts.yaml文件中（facts 节点读取 02_template/标书模板.docx 表格，提炼入 GlobalFacts.template_fields）
- [x] 在填写表格时，优先使用facts.yaml 设置的企业信息和名称（三 fill prompt 明确取值优先级：template_fields/企业资料 > metadata > kb）
- [x] 当前fill阶段耗时较长…为填写表格/填空/插入图片 的skill…（已封装 src/biaoshu_gen/fill_skill.py：前缀锚定 fill_blank/fill_cell/replace_in_para/insert_picture_after/WEBP 转码；fill_blank 修复"值附加在下划线之后"——优先填带下划线空白 run/替换下划线字符 run 留余线/复制格式插入带下划线 run；合成模板单测 4 项通过；prepare_agent_workspace 自动投放 skill 到三个 fill 工作区并写入 prompt）
