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

- [x] extract_template 节点当前是使用harness方案，这种方法性能和稳定性都较差，该节点本质是找出模板文件/响应文件 在原始招标文档中的启示和结束锚点，在使用python脚本剪裁就可以了，修改该节点使用非harness方案，并使用@data/tender/软件招标文件.docx 和 @data/tender/标准的招标文件.docx 进行测试（已改 LLM 定界+python 整包副本删区间：块化后单次 PydanticAI 调用返回起止块序号，代码硬校验重试一次封顶；template.md/report.md 由剪裁副本确定性派生零 LLM；随附响应模板存在时直接复制为底稿。两份真实样本验收通过——LLM 定界精确且两次独立运行字节量一致，全量测试 136 passed）
- [x] 在fill阶段之前 应该先拆分响应模板文件，分别拆分四个部分：偏离表部分，技术/实施方案部分，表格填写部分，其余商务填写部分（template 阶段新增 split_template 节点：有标题按关键词规则归类、无标题 LLM 分段兜底，clip_docx_keep 多区间保留物理拆分产出 parts/ 四份 part+parts.yaml；fill 三节点各用对应 part 缺失回退整模板；assemble 主路径改为按文档原序顺序拼接，锚点匹配/去重兜底退役为无清单回退）
  1. 后续三个节点分别在以上三个不同的文件中操作
  2. 将正文放到技术/实施方案部分docx中
  3. 按照拆分时标记的顺序组合四部分的docx
- [x] fill 阶段中的form节点可以参照deviation节点改造提升速度，不再使用harness，（LLM 直出 FillOp 填写计划 + python 经 run_fill_plan 确定性执行，执行报错带反馈回炉≤2 轮；离开 flash/DSML 不稳定通道）
- [x] parser阶段考虑使用并发解析出各个部分的信息（2026-08-28：全部(组,批次)抽取任务入线程池并发(≤6),按提交序收果保合并语义;屏障回归测试锁并发性）
- [x] assemble需要保证拼接时 技术/实施方案的 目录层级结构（2026-08-28：正文注入按锚点层级降级——锚 H2 时正文 #→H2/##→H3,markdown_to_docx 增 heading_offset;主/回退路径均接线,回归测试断言样式级）
- [x] 在标书元数据中增加对 标书类型的判断 分为三类  服务/货物/工程（metadata 组抽取 prompt 三选一主判 + 代码侧关键词兜底 _infer_bid_type——特异性序工程>货物>服务，「货物及服务」判货物；TenderMetadata.bid_type 归一化校验器收「货物类/建设工程」等变体、未识别留空；随 metadata.yaml 落盘，供采购清单/方案编写按类型路由）
- [x] 在解析招标文件 parse tender的节点中，classify_sections 应该允许某个章节属于多个classification， 项目概况 应该即可以提供元数据信息 也可以提供需求侧的信息（多组归属本就支持——同节可入任意多组且有双组测试锁语义；本次补「项目概况」入 metadata 组关键词，与 requirements 双归属，双组归属测试锁定）
- [x] 提供一个重跑某个阶段的命令，比如parse阶段我不满意 修改了代码 然后我可以重跑parse阶段（rerun <stage> 已存在；本次补齐 parse 特例——原实现对首阶段直接拒绝，现清空当前 checkpoint 从头重跑（GC 释放 sqlite 文件锁+DROP TABLE 兜底），后续阶段仍可经各自 checkpoints/<stage>.sqlite 备份重跑；回归测试断言 parse 节点二次执行）
- [x] 如果是一个货物类标书，在facts.yaml中应该有货物名列表的placeholder（GlobalFacts 新增 goods_list 字段；facts prompt 按标书类型指导填写——仅货物类从采购清单/项目概况提炼产品名；节点确定性兜底：货物类且 LLM 未填时用 requirements.purchase_list 预置 placeholder，人工可编辑；非货物类保持空列表，三场景测试锁定）
- [x] 如果是非货物类的标书 则在写标书正文时不再参考知识库 search_snippets 应该跳过（rich_body 检索策略：metadata.bid_type=='货物' 才调 search_snippets，服务/工程类零检索；货物类按二级单元聚合检索——query=二级标题+描述+其下全部三级标题，整单元共享材料，二级 target_words=叶子之和实算进树；正文按三级小节粒度并发（用户裁定，曾按二级实现后改回）；测试覆盖零调用/query 构成/材料进 prompt/合计进树/叶子级屏障并发）
- [x] 新写一个rich_body_v2 模块，里面和LLM交互统一为二级标题，但是要求LLM返回时按照三级格式返回，包括media need 和 body section，后续插入的table / figure 还是按照三级标题上下文插入，注意在知识库检索阶段需要将二级标题下的所有三级标题也都拼到prompt中（nodes/rich_body_v2.py：媒体需求 UnitMediaNeeds/正文 UnitBodies 均按二级节一次调用、返回逐条 sec_id 对位到三级小节；表格/图片生成与插入沿用 per-leaf 原语（三级上下文）；货物类检索 query=二级标题+描述+全部三级标题整单元共享；叶子文件仍按 {sec_id}-{标题}.md 落盘、body.md 树状拼装、fix 只写回被点名小节；prompts/rich_body_v2.py 单元级 prompt；7 个测试：二级调用次数=单元数/sec_id 对位/清单完整性/检索聚合/非货物零检索/fix 语义/续跑/媒体插入。未接入 graph 注册表——与 rich_body 并存，切换时改 nodes/__init__ 一行）
- [x] rich_body中的medianeed判断只需要做一次，也即是在body review后不应该再次触发media need（判定结果落盘 05_body/media_needs.yaml：{sec_id: {type, score}} 含 none 判定；rich_body 与 rich_body_v2 重入（review 回环/续跑）均从缓存恢复 leaf.media_type/score，仅对无缓存的新叶子（目录新增）触发判定后增量写回；测试断言回环后 MediaNeed/UnitMediaNeeds 零调用）
- [x] 第6 阶段 fill 不再区分 fillform和 commercial ，合并这两个节点，也就是在body_review完成后只进行deviation_table 和 fill_form, commercial 被合并到fill form中，因此在第二步 template时 只需要解析出技术方案部分和偏离表部分，其余部分作为一个整体，该部分先进行程序化的填写再使用harness兜底（2026-09-08：split_template 四分改三分——deviation/technical/forms(catch-all=投标函/报价/资格/商务整体，part 名"其余填写部分.docx")；commercial 节点删除，graph/注册表/软失败/state 字段/assemble 回退同步收敛，fill 阶段只剩 fill_forms+deviation_table；fill_forms 承接其余整体：先程序化（预填+LLM FillOp plan+run_fill_plan 确定性执行，prompt 并入商务响应语义、build_fill_context 注入企业信息摘要），plan 两次校验失败/LLM 通道挂/执行报错时转 harness 兜底——同工作区 agent 打开既有产物补填（prompt 带报错清单或全量指令+当前产物地图），兜底失败不弃产物记 error.log；全量 223 passed）
- [x] 在 assemble阶段， 技术或实施方案中的图表 应渲染后再合并起来，否则word中无法正确显示表格和mermaid图（2026-09-08：markdown_to_docx 块级解析（围栏优先，围栏内不再按标题/表格误判）——管道表格→真 docx 表格（Table Grid+表头加粗，无分隔行的孤竖线行不误判）；mermaid 围栏→render_mermaid_png（mmdc -b white -s 2，与 render_check 同环境探针，缺失/失败返回 None 降级代码文本不阻塞装配）；注入经 scratch 文档搬运后 adopt_image_rels 迁移插图关系（否则 Word 显示空白）；本机按 repo 文档装 mermaid-cli（PUPPETEER_SKIP_DOWNLOAD + 系统 Edge），真实渲染 E2E 验证 PNG 入包）
- [x] 在assemble 阶段，技术或实施方案中的三级目录应该有相应的编号和大纲级别 如 1. 就应还是H1 级别  1.1 应该是H2 级别， 1.1.1 应该是H3 级别，并将章节号附在标题前（2026-09-09 终版：编号与层级解耦——number_headings 恒为 #→「1.」/##→「1.1」/###→「1.1.1」（同级递增、升级清零、围栏内行跳过，不随锚变深）；层级按锚点挂接（锚 H4 时正文 #→H4/##→H5/###→H6，经 w:outlineLvl 直写段落属性，导航窗格/目录嵌在宿主「技术部分>技术方案」之下）；标题样式跨包语义对位（解析名→大纲级别→合成兜底）；另修 replace_elements 空区间 no-op 致锚标题切片正文静默丢失——空区间改插锚标题后）
- [x] word中表格的样式 没有（2026-09-09：机理同上——生成表格的 tblStyle=TableGrid 引用在真实模板 styleId 体系下悬空，Word 显示无边框裸表；边框改为 w:tblBorders 直接格式写入（六边 single 0.5pt），随元素跨包搬运不依赖宿主样式表，Table Grid 样式引用保留为宿主包有同名样式时的叠加；真实 run v2 草稿 9 表全部带直接边框验证）线框，同时mermaid 图渲染后如果过大，会部分不显示，设计一个图片缩放的功能
- [x] table caption 或者是 figure caption 应该自动打上序号 如 表1. 或 图1. 并且需要在水平方向置中（2026-09-09：markdown_to_docx 题注识别双轨——显式前缀（图：/表：，_render_media 产出已带前缀）+ 裸名词短语启发式（紧随媒体块、≤30 字、无句末标点、非列表行，兼容存量 body.md）；自动编号「表N./图N.」表图独立计数、已有编号规一化重编，段落水平置中；真实 run v5 草稿 6 题注（图1-3/表1-3）全部编号居中）
- [x] 当前技术方案知识拼接在了word的末尾，我需要它处于正确位置 后续的部分也不能丢（2026-09-09：取证 parts.yaml 交错 run 序（forms 0/technical 372/forms_2 377）与块级位置——正文本就按文档原序注入锚槽（块 375/860），非物理拼接在末尾；观感问题根源是正文以 H1 顶层级别横插在格式章 H4 槽位，导航/目录里技术章节与「第七章」平级、读作另拼的一份文档。修复：层级按锚挂接（outlineLvl 3/4/5 嵌于「技术部分>技术方案」下），编号不变；后续部分（其他技术文件/落实政府采购政策声明函）原序保留在 801+ 验证无损）
- [x] 大纲和正文之间的行距要设置一下（2026-09-09：模板自带标题样式本就有段距（如 H4 段前 280/段后 290 缇），挤的是合成兜底样式与样式缺失回退段——ensure_style_fallbacks 合成样式补 段前/段后 260 缇（13 磅，对齐模板 H2/H3 惯例）+ 行距 360（1.5 倍与正文一致）；markdown_to_docx 样式缺失回退的普通段落标题补直接段距；顺修 add_heading 先建段后设样式的孤儿段落 bug——缺样式时标题文本曾重复两份；v6 草稿验证 H5/H6 带段距加粗、模板 H4 沿用自带段距；全量 257 passed）
- [x] 当前生成结果中 图片并没有在水平方向居中（2026-09-09：_add_mermaid add_picture 后将图所在段落 alignment 置中（#84）；真实草稿重生成验证 3 图全部水平居中）
- [x] 当前fill阶段picture的插入效果不佳 将这一类型的操作放到harness中进行（2026-09-09：picture 类 op 整类型退出 python 确定性通道——fill_forms 执行前剥离 pictures，存在即触发 harness 兜底，prompt 单列【待插入图片】清单（锚段/绝对路径/图注/宽度），agent 对照产物实况插图并自检位置与大小（fill_skill.insert_picture_after 可用）；兜底失败不弃产物，error.log 记 picture 待插清单；run_fill_plan 的 picture 原语保留供 harness 工作区脚本使用）
- [x] 比较以下 @data/runs/run-20260909-094732/07_draft/标书草稿_v1.docx  和 模板 @data/runs/run-20260909-094732/02_template/标书模板.docx 中的磋商响应声明，当前的填写效果对下划线后接（）的方式支持不太好，提出解决方案（2026-09-09 取证草稿段20：fill_blank_before_label 填空位后保留「（标签）」注记，产出「实训室（项目名称）的磋商邀请」值/标签叠读。修复：填值后清除紧随的「(label)」括号对——同 run 仅删首个括号对、其余文本（如「的磋商邀请（政府采购编号：」）与后续下划线空位不动；多标签括号（如「（姓名、职务）」「（项目名称、政府采购编号）」）维持不填、留给 replace 整体替换；效果「根据贵方为演示项目的磋商邀请（政府采购编号：__），」）


- [x] assemble阶段 data/runs/run-20260909-173416/07_draft/标书草稿_v1.docx 的1.2.2章节中的流程图被替换成了身份证的图（2026-09-10 取证：终稿 1.2.2/2.4.2/3.1.2 三处 mermaid 插图的 r:embed 全指向 rId16/17/18——forms 桶（身份证/营业执照/信用截图）先装配占用的同号关系，mermaid PNG 根本没进终稿包。根因两层，同出 adopt_image_rels 的 img_cache：①缓存按裸源 rId 字符串为键，而 assemble 的 cache 跨全部源文档共享，各文档 rId 命名空间独立、同号即撞车；②缓存值是「某一次调用那个 dest」的 rId，assemble 技术桶两跳（scratch→part→终稿）dest 不同，第二跳把 part 命名空间的 rId16 直接填进终稿。修复：缓存键改图片内容 SHA1、值改 (dest part, rId) 二元组，命中须 dest 同一对象才复用（part 引用同时钉住防 GC 地址复用），否则 get_or_add_image 重注册（同 blob 幂等）；同内容跨桶仍去重为同一 rId。回归测试覆盖同号撞 rId 与两跳链两形态；rerun assemble 验证 1.2.2 出图6.png（mermaid 渲染的协同方案流程图）+ 题注图1.，2.4.2/3.1.2 同修，资格文件区图片原位不动；全量 268 passed）
- [x] fill阶段填入的身份证图片位置不对（2026-09-11 取证 run-20260909-173416：模板的证照粘贴位是单元格文字为「xxx复印件」的单列框表——附件2-1-1 单格框「身份证正反面复印件」、授权委托书 2 行框「代理人/法定代表人身份证正反面复印件」；harness 插图 agent 却把图+自创图注插在框外段后（「附：…复印件。」「本授权书于…」），框全部空置且图注与框内标签文字重读；同因资质证书/专利证书整体漏插（12+ 张 kb 图只插 6 张）。原因链四层：①可填点地图把框表当"文本批量填表"列出，无粘贴框语义；②insert_picture_after 只有段后插图，没有进表格单元格的原语；③prompt 写死单一工具且"含图注"鼓励自构图注；④自查只验证"图跟在哪段后+宽度"，验证的是自己的决定而非模板意图。修复三件套：fill_skill 新增 insert_picture_into_frame（按行内文字定位单列框行、图插格内、标签保留、已有图幂等跳过、只认单列表）；插图 prompt 重写——粘贴框必须进框且禁止自创图注、无框小节才段后插图且图注只抄模板原文词、自查改为逐框有图/无自创图注/kb 逐张有着落；fill_context 新增 picture_anchor_hints 预匹配清单（kb 图片名↔框行/小节标题的确定性建议：法人身份证→法定代表人框行、授权代表→代理人框行、营业执照→附件2-2、信用→信用信息、资质/专利→附件2-4，无匹配标「无建议」交 agent 兜长尾），_picture_pass 注入产物级锚点。测试 +3；全量 270 passed）
- [x] 你测试过了吗——fill 插图链路真实端到端复测暴露三缺陷并修复（2026-09-11：①GBK 控制台/重定向下 print("ℹ/⚠") 抛 UnicodeEncodeError 杀死节点——实测后台管道下主 forms 的插图 pass 整个没跑、graph 照常走完表面"成功"；修复：cli.main 入口把 stdout/stderr 统一 reconfigure UTF-8 容错替换（进程内 print 与控制台编码解耦），fill_forms 两处进度 print 改 log.info。②run_harness_task 只校验「产物存在」，防不住 harness 会话「成功」返回但零工作——实测 deepseek flash 9~13 轮即在任务中途提前收回合（末句「现在分析预匹配清单：」），产物零新增图照样判过；修复：插图 pass 后按 inline_shapes 新增数做内容级校验，空跑重试一次、仍空记 error.log 附预匹配待插清单（不弃产物）。③附加段切片（forms_2 等）无任何可挂锚点也照跑 harness 空转——预匹配清单兼作触发门槛，全「无建议」直接跳过（实测省一次调用）。测试：假 harness 升级为真插图（内容级校验需要），+2 用例（无锚点跳过/空跑重试记错）；全量 272 passed；真实 run 复测：门槛跳过、空跑检出重试、error.log 待插清单全部按设计触发。遗留：harness 模型 deepseek-v4-flash 当日两轮均提前收回合未完成插图（前一日同配置可完成）——管线已把该失败从静默变为响亮，建议 HARNESS_MODEL 换更稳的档位）
- [x] fill 阶段 harness 思考力度强制 high 试试（2026-09-11：#89 遗留的 flash 档中途收回合问题——claude-agent-sdk 0.2.x 的 ClaudeAgentOptions 有 effort 字段（low/medium/high/xhigh/max，配合 adaptive thinking 引导先想清再动手）。新增 HARNESS_EFFORT 配置默认 high（归一化：非合法值置空=不传），_query_sdk 传入。真实 rerun fill 复测：插图 pass 单次通过新增 9 张图（此前连空两轮），身份证 3 张全部落进粘贴框对应行且标签保留，营业执照/资质/专利/信用 6 张全部挂模板原文小节标题后、零自创图注，两个 FormsFill plan 均 0 报错；assemble 终稿验证粘贴框进图+正文 3 张 mermaid 完好，全链路正确）
