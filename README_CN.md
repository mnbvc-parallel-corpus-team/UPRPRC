# UPRPRC 中文说明

本仓库是 [MNBVC](https://github.com/esbatmop/MNBVC) 平行语料小组的，生产来自 [United Nations Digital Library](https://digitallibrary.un.org/) 文件的6国语言平行语料的管线脚本。

本管线涵盖了以下步骤：

1. 从搜索系统中按年份爬取所有文件的列表
2. 下载会议文件
3. 将文件转换为文本，输出文件级对齐语料
4. 对不同语言间的文本文件进行段落级对齐，输出双语段落级对齐语料
5. 对双语段落级语料进行合段，输出全语种段落级对齐语料

成品语料: 

- [https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20230240](https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20230240)
- [https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20250102](https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20250102)
- [https://huggingface.co/datasets/bot-yaya/rework_undl_text](https://huggingface.co/datasets/bot-yaya/rework_undl_text)
- [https://huggingface.co/datasets/bot-yaya/undl_ar2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_ar2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_de2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_de2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_es2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_es2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_fr2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_fr2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_ru2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_ru2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_zh2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_zh2en_aligned)

2025/09/14 跑新管线得到的全量语料

- [按发布日期升序排列的UNDL全站所有文件表](https://huggingface.co/datasets/bot-yaya/documents.un.org_search_result)
- [全量PDF文件](https://huggingface.co/datasets/bot-yaya/UPRPRC_pdffiles_from_UN)
- [全量DOC文件](https://huggingface.co/datasets/bot-yaya/UPRPRC_docfiles_from_UN)
- [段落级SBD分句缓存](https://huggingface.co/datasets/bot-yaya/UPRPRC_SBD_KV)
- [句子级机翻缓存](https://huggingface.co/datasets/bot-yaya/UPRPRC_TR_KV)
- [文件级对齐语料，从doc导出并且特别处理了表格结构的文本](https://huggingface.co/datasets/bot-yaya/UPRPRC_FTXT_FILEWISE)
- [双语段落级对齐语料](https://huggingface.co/datasets/bot-yaya/UPRPRC_BILINGUAL)
- [全语种段落级对齐语料](https://huggingface.co/datasets/bot-yaya/UPRPRC_BLOCKWISE)

## 管线总览

![Overview of UPRPRC](charts/flowchart.jpeg)

## 安装依赖

我们推荐在一台装有 `Python 3.9+` 的 `Win10 21h2+` 机器上运行整条管线。管线会用到 `Office` ，确保安装有2019或更新版本。

```bash
cd scripts
pip install -r requirements.txt
```

## 管线执行

### 单机用例

对于那些只是希望完整把整条管线运行起来，不在乎生产效率的单机用户，可以遵照 [scripts/new_sample_all.py](scripts/new_sample_all.py) 里定义的执行顺序，一步步按顺序执行这些py脚本。

首先修改 [scripts/const.py](scripts/const.py) 文件。

1. 将 `GET_LIST_FROM_YEAR` 和 `GET_LIST_TO_YEAR` 分别设置成想要爬取的文件的年份。
2. 如果你想要修改中间文件的输出目录，可以修改 `WORK_DIR` 以及所有依赖它的文件路径，但我们不推荐修改这些配置。

> 我们建议将 `GET_LIST_FROM_YEAR` 和 `GET_LIST_TO_YEAR` 两个变量设置成相同年份，对每一年重复执行整个管线，以达到年份分批的目的。

```bash
cd scripts
# 根据给定的 GET_LIST_FROM_YEAR 和 GET_LIST_TO_YEAR ，爬取对应年份的文件列表
py new_sample_get_list.py

# 根据上一步得到的列表，批量下载 doc 文件
py new_sample_get_doc_async_candidate.py

# 将上一步得到的 doc 文件批量转换成 txt ，同时生成文件级对齐的 filewise_result.jsonl 语料
py new_sample_doc2txt.py

# 将上一步得到的 txt 的非英语语种文件按段落翻译成英语
py new_sample_txt2translate.py

# 将上一步得到的翻译将非英语语种和英语文本做对齐，应用 GAPA 算法，同时生成双语段落级对齐的 alresult_dataset 语料。注意它是 huggingface dataset 文件
py new_sample_translate2align.py

# 将上一步得到的双语段落级对齐语料连边合段，做成6国语言对齐的 blockwise_result.jsonl
py new_sample_align2mergedjsonl.py

```

### 效率瓶颈及其优化方案

文本翻译是整条管线中，最耗时、耗费算力的一个步骤，大约占了整条管线执行耗时的 99.1% 。所以我们针对性地对其做了分布式优化。

我们推荐拥有多台机器、拥有安装有多路CPU的服务器、拥有安装有多块独立显卡的机器、拥有多台云服务器或者 colab 付费计划的用户执行 `py new_sample_txt2translate_distrib_candidate_server.py` 来部署翻译任务分发服务器，并且在算力富余的机器上面运行 `py new_sample_txt2translate_distrib_candidate_client.py` 来分布式执行机翻，以分担 `new_sample_txt2translate.py` 这一步骤的任务，缩短整个翻译步骤带来的时间开销。

根据我们在 2023 年的实践，我们给出针对分布式机翻这一步的推荐部署方案。谷歌云机器配置选择推荐可以参见 [bot-yaya/undl_en2zh_translation](https://huggingface.co/datasets/bot-yaya/undl_en2zh_translation) 的 README 部分。

- 分布式任务执行之前，确定好 `const.py` 里配置的 `TRANSLATION_SERVER_PORT` ，并且同步修改 `new_sample_txt2translate_distrib_candidate_client.py` 及其衍生脚本里写死的端口号，以使其匹配。
- 选一台能够方便访问到的服务器，执行 `py new_sample_txt2translate_distrib_candidate_server.py` 以部署任务分发服务器。如果你并非在局域网内部署整套系统，又没有公网ip，你可能需要自己准备一台有公网ip的云服务器或一套端口转发方案。注意确保这台服务器的储存空间够用，翻译步骤的中间文件是没有压缩过的 `pickle` 序列化文件。我们在跑 2000-2023 年的数据时是用了一台腾讯云服务器和 [nps](https://github.com/ehang-io/nps) 做反代。
- [argos-translate](https://github.com/argosopentech/argos-translate) 既可以在CPU上运行，也可以在GPU上运行。对于安装有独立显卡的机器，可以反注释掉 `new_sample_txt2translate_distrib_candidate_client.py` 的 `os.environ['ARGOS_DEVICE_TYPE'] = 'cuda'` 这步来使用 cuda。如果有多块显卡，可以写成 `cuda:0` 这种形式来指定设备号。这些机器在使用显卡执行翻译任务的同时，还可以多执行一个使用cpu翻译的实例。`argostranslate` 并不能完全榨干显卡的算力，并且有时会有cpu翻译节点比gpu快的情况。
- 对于多路CPU的服务器，有几路CPU就启几个 `new_sample_txt2translate_distrib_candidate_client` 。否则其它路上的CPU不能被利用
- 对于 google 账号比较多、或者 colab 的付费用户，我们准备了 `new_sample_txt2translate_distrib_candidate_client_for_colab.ipynb` 脚本。这是一个在 google colab 环境中即开即用的 `jupyter notebook` 文件。注意每个免费用户可以同时执行3个任务，请复制3份这个文件来使用。
- 对于在 [Google Cloud Platform](https://cloud.google.com/) 或者其它云服务商上有多台虚拟机实例的用户，我们准备了 `new_sample_txt2translate_distrib_candidate_deploy_debian12.sh` 脚本，方便直接在对应环境中执行一键命令直接令当前机器参与翻译。甚至是谷歌云或者阿里云的 `cloud shell` 中你都能利用这个脚本直接执行翻译任务。但注意不要直接执行这个脚本，你可以打开这个脚本有选择的使用前半部分或者后半部分。
- 在 server 已经没有任务可以下发后，**别忘了在最后执行一次** `new_sample_txt2translate.py` ，它会把翻译完成的文本 pickle 缓存做成能够给管线的下一步使用的 dataset。
