1. 当前各个节点输入较慢 主要原因在于 使用LLM时 prompt较长，生成的output也长，考虑并行执行，如在facts阶段，
template_fields 字段可以另行使用LLM调用抽取，在抽取 template阶段，也应该只需要传入outlines,当然现在抽取的效果不错，
只传outline的话需要进行测试

2. 没有prompt cache的管理，好像配置deepseek 的endpoint有点问题
3. 当前调试阶段串行执行完整个流程较长，在集成测试阶段可以并行化处理，parse和template并行 (facts+outline+body) 可以和fill阶段并行，然后再assemble
