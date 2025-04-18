from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tiktoken")
hiddenimports = [
    "tiktoken_ext.openai_public",             # core
    "tiktoken_ext.openai_public.cl100k_base", # needed for 'cl100k_base'
    "tiktoken_ext.openai_public.r50k_base",   # needed for 'r50k_base'
    "tiktoken_ext.openai_public.p50k_base",   # needed for 'p50k_base'
    "tiktoken_ext.openai_public.gpt2",        # needed for 'gpt2'
]
