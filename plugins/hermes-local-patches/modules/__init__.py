"""hermes-local-patches modules — 自动发现 + 加载所有模块

每个 .py 文件 = 一个补丁模块，自动被 loader 发现和加载。
标准接口: NAME, DESCRIPTION, apply(), revert(), is_applied()
"""
