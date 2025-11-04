喜报，我们拖了两年的论文终于写完投出去了，然后还挂上了 [arxiv](https://arxiv.org/abs/2509.15789) 。

> Who are you? Please \cite{UPRPRC} ☝️🤓

# 记点流水账

先给各位介绍一下， UPRPRC 是我们整套把联合国数字图书馆 (UNDL) 的数据从**原始数据下载**到整理好成为能直接拿去喂机器翻译模型的**平行语料**的一系列脚本。这份脚本初版是在 2023 年年底完成并且跑了 2000-2023 年间的数据。当时觉得我写了啥就提交啥就是开源，现在我自己看[当年写的](https://github.com/mnbvc-parallel-corpus-team/parallel_corpus_mnbvc/blob/b07acdab9d04855573a4ad2ac4382e2e5b4293f9/convert_data/doc2text_poc.py)都不知道我在写什么玩意，所以后面意识到这个问题，整理了一版至少前后逻辑能理清楚的~~用来写论文~~拿来发布，做得真的想要给别人用。

当时工程落地组长问了一嘴要不要写个论文说下你的工作，反正咱们也是延续前人 [un1.0](https://www.un.org/dgacm/sites/www.un.org.dgacm/files/files/UNCORPUS/un.pdf) 的工作来的。我答应了，然后因为完全没有经验把这个工作量比我毕设大得多的玩意写成正经论文，前后拖了一坤年，期间为论文跑评测数据的时候还被挑了个刺，说为什么会有一堆对不齐的表格符号，然后专门针对这个表格问题写了特殊处理的代码。当时也挺好奇前人工作是怎么处理表格的，让组员翻了下他们数据，发现他们没处理，就是坏的。

然后咱们把表格处理弄好了，但是[老数据](https://huggingface.co/datasets/bot-yaya/rework_undl_text)还是坏的，怎么办，我说要不重跑吧，遭到反对意见，说是不要改一点东西就整个重跑。但想想部署这些东西也就我一个人做，挂着跑又不占我工时，顶多占用机子性能不能打游戏，那要不还是跑吧。但是这事不出意外的让我给忘了，笑死。后面应该只是按年增量跑24年数据的时候加上了这个处理，但这份数据我没有单独传 hf，而是跟着 [liwu/MNBVC](https://huggingface.co/datasets/liwu/MNBVC) 那个仓库走的。说实话我也不知道我给文件之后他们放哪了。

后面回头写论文去了，文书工作弄到一半的时候感觉这图表怎么看怎么不对。准备好收拾收拾第二次完整地跑一遍UPRPRC，这次跑全量数据，能爬到多少跑多少，正好把表格处理也整合进去。

感觉之前管线部分爬搜索结果按年爬的不是很好做增量爬虫，再说之前看数据发现去年前年的文件在今年还有新增的，神秘。所以要不干脆就重做一下爬虫。这就是 v2 开头的脚本和 v2_record_spider 分支的来由。

首先观察到 `digitallibrary.un.org/record/` 这个站可以直接枚举 record_id 来取到文件语言和 symbol 信息。并且 record_id 一定是从1开始的，而且是连续的。所以 v2 脚本就从这里入手直接去枚举 record_id 来爬。爬一半发现异步并发爬会受到 HTTP 202 限流，弹验证码。搞不定这个，然后写了个 C-S 架构的分布式爬虫利用手上的其它机器。然后机器挂着，人去研究爬来的数据能不能下文档。然后结果不出意外的错误率很高。3台机器挂一天才差不多得 10000 份文件，其中只有 1000 来个文件是有效的，而且它网页上提供的 symbol 号还带一些比如 `^` `[]` 这种会引起下载文档那个 api 报错的符号，需要做转义，而且还不知道转义后还能不能找到这个文件，至少我试了大多数都是不行的。然后这种方法继续挂着，人去研究 v3 爬虫了。

找以前爬文件的兄弟问了问当年是怎么爬的，为什么图表上 2015, 2016 年的文件缺了一大块。

说是当年好几个人合作干的这事，直接下载的 sitemap 文件，然后依据这个东西传了个 [huggingface](https://huggingface.co/ranWang/datasets) 数据集，然后用另外一个脚本（已经找不到了）对着 symbol 下载

现在能找到的下载文件表的脚本是 https://github.com/mnbvc-parallel-corpus-team/parallel_corpus_mnbvc/tree/main/download_data/un_corpus_pdf_sitemap

但是现在的UPRPRC下载文件是按 symbol 和对应的语种下载的。我重新用下载 sitemap 的方式爬了一遍，全量 sitemap 只需要下载5分钟，但是这次拿正则匹配匹出来的语种和文号再拿去爬文件，命中率更是低的离谱。

所以 v3 脚本放弃研发，我去 [documents.un.org/api/search](documents.un.org/api/search) 这个地方拿文件表，因为它正常用户流程就是从这里得到表然后根据 job_number 取到对应文件的，这个搜索结果给的结果应该是可靠的，只是之前一直没试出来取全量数据是靠 job_number 传个 `*` 号。正好之前搞出来过一个打表法能过 Authorization ，这样一来 v4 脚本就容易落地了。

所以现在的 v4 脚本就是一边跑全量一边更新迭代的管线，下一节介绍一下脚本的执行顺序，以及和初版脚本之间的区别。

# 怎么部署的 UPRPRC

管线的执行流程总的来说是没有变化的，但是初版管线有一个问题，必须等待所有上一步的任务执行完成，才能执行下一步。这一点在跑全量数据的时候挺浪费时间的，因为我谷歌云试用用完了，手边的机器只有一台不能装 Office 的 Zen4 高配机 `kuso`、一台用了5年的 Zen3 高配家用机 `Kaguya`、一台买来打舞萌时排大逼队打游戏的 7840U GPD WIN MINI 小电脑 `erina`、一台刚买的幻X 2025 `sAlt`，后三者可以部署 doc 转 docx 任务，另外算上云资源的话还有一台 2C4G 的腾讯云 6133 `chuchu`，一台阿里云 2C2G 大带宽机 `elsa`，还有一台树莓派5 `PieBerry` 不知道能不能算得上战力，还有国庆回家用了一下老家的电脑 `Murasaki`。

总之这里还是给出一个机器配置表：

| 机器名 | 配置 | 备注 | 翻译步骤贡献算力 |
| --- | --- | --- | --- |
| Kaguya | 5800X, 3090, 128G RAM, 1+2T SSD + 一大堆 HDD | 分布式任务开始的地方 | 算力拿去跑 sbd 去了，没跑翻译 |
| kuso | 7950X, 4070Ti, 128G RAM, 1+4T SSD | 不能装 Office, 有大带宽网，涉及爬虫和上传任务我都放在这里 | 1600 + 10000 tk/s |
| erina | 7840U, 核显, 32G RAM, 512G SSD | GPD WIN MINI, 导 docx 时蓝屏过三次 | 2000 tk/s |
| sAlt | AI MAX+ 395, 8060S, 64G RAM, 1T SSD | 幻X笔电，为了不打扰他人始终开启节能模式。因为 AMD 对 pytorch 支持没跟上所以没用上核显算力 | 2200 tk/s |
| chuchu | Gold 6133(只有2核), -, 4G RAM + 4G swap, - | 腾讯云服务器，搞端口转发用，作死让它也跑了一下翻译，结果内存不足把转发给卡炸了，亏了我一天工时 | 220 tk/s |
| elsa | Platinum 型号未知(只有2核), -, 2G RAM + 4G swap, - | 阿里云服务器，有百兆带宽，后来买的，搞转发用，也跑了下翻译，但受限于内存，跑得很慢 | 120 tk/s |
| Murasaki | 2600, 2080Ti, 32G RAM, - | 只是因为测速目的稍微跑了一会 | 800 + 8000 tk/s |


管线的主要开销在 `doc 转 docx` 和 `txt 翻译` 这两步。前者需要装有 Office>=2019 版本的 Windows，后者对系统没要求，但最好是内存大于等于 4G 才够用。

运行顺序：

| 脚本 | 部署方式 | 备注 |
| --- | --- | --- |
| v4_use_docunorg_for_list.py | `Kaguya` 单进程 <br> asyncio 单 task | · 部署前记得先去 #3 这条 issue 里面看一下打表方法，拿到表后填写表文件路径再开始跑 <br> · asyncio 开多个 task 爬会报 403，只能慢慢等 <br> · 不要动分页参数，实测改每页个数会导致请求的数据重叠，举例来说你改成一页 50 个，然后它第一页会给你 0~49, 但第二页给你 20~69 <br> · 爬完直接把文件列表传 hf，仅备份和校验用，管线不会用到 <br> · 每个分页查询请求会记一个缓存文件方便后续流程得到文件结构组织 |
| v4_list2doc.py | `Kaguya` 单进程 <br> asyncio 32 个 task | · task 不是越多越好，实测 24~32 个就能飙满，下载带宽最大只有 1M 左右 <br> · 这个脚本直接调用了 `new_sample_get_doc_async_candidate.py`，所以改 task 个数也是直接在后者里面改 `WORKERS` <br> · 可以跟 v4_use_docunorg_for_list 同步部署，把 `while 1` 反注释掉可以让它轮询目录，下了多少文件列表就拿着多少列表去下文件 <br> · 每个下载下来的文件以 job_number 直接命名，例如 `N010492.doc` <br> · 按文件种类 doc, wpf, wpd, pdf 分类，其中 pdf 不是适合本管线处理的类型，直接丢弃 |
| v4_doc2docx_svr.py | `Kaguya` 单进程 | · 发布 docx 转换任务，请求时扫描目录，有几个 doc 就处理几个，也顺便把 wpf 和 wpd 处理了 <br> · 已经改成来一个处理一个的流水线模式，对于每个 doc/wpf/wpd 存一个同名的 docx |
| v4_doc2docx_client.py | `Kaguya` 单进程 <br> `erina` 单进程 <br> `sAlt` 单进程 | `WINWORD.exe` 是操作系统级单例，没法通过多进程来利用多个核。如果你确实想用，可以考虑虚拟机里装 Office 来跑脚本，实测确实能利用其它核的算力用于导出 docx，但有调度开销，不建议多少个核开多少个虚拟机 |
| new_sample_doc2txt.py | `Kaguya` 单进程仅调用 `docx2txt` <br> `Kaguya` 单进程仅调用 `txt2flatten_txt` | · `docx2txt` 进程负责调 `pandoc`，`txt2flatten_txt` 负责处理表结构，这两步比 doc 导 docx 快得多，虽然脚本设计上加了多进程，但实测单个就够用 <br> · 已经改成来一个处理一个的流水线模式，对于每个 docx 存一个同名的 txt |
| v4_txt2sbd.py | `Kaguya` 6 进程 | 把段落级文本打散成句子级，单进程提交用不满显卡吞吐，所以单独把这步拆出来，接上 lmdb 缓存，这步缓存可以显著减少相同段落分句带来的不必要开销 |
| v4_sbd2tr_tcps.py | `Kaguya` 单进程，每 128 个句子打批作为一个任务分发下去 | · 分发 sbd 分句的结果去机翻，写到 tr 缓存里，这步显著减少了相同的句子带来不必要的重复翻译开销 <br> · 对于每个段落，连同其语种简写计算其 sha256 作为 key， 服务器侧利用此 key 缓存压缩后的分句结果至 lmdb，对于客户端的回传也是相同方法进 lmdb 做句子级缓存 <br> · 前身为使用 http 的 `v4_txt2tr_svr.py`，因为实际部署中发现端口转发至公网后有请求方法不对的恶意请求，故修改为带简单校验的 tcp <br> · 总计约 3w 个爬虫分页信息表，其中按现在的系统一天能消化大约 2500 个信息表的文件，预计 12 天做完  |
| v4_txt2tr_tcpc.py | `kuso` cuda & cpu <div style="text-indent: 1em;font-size: 9pt"> 4070Ti~10000 tk/s \| 7950X~1600 tk/s</div>  `erina` cpu 单进程 <div style="text-indent: 1em;font-size: 9pt"> 7840U~2000 tk/s</div> `sAlt` cpu <div style="text-indent: 1em;font-size:9pt">AI MAX+ 395~2200 tk/s</div>  <div style="text-indent: 1em;font-size:9pt">由于构建 [TheRock](https://github.com/ROCm/TheRock) 失败，无法使用 8060S</div> `chuchu` cpu <div style="text-indent: 1em;font-size: 9pt"> Gold 6133(2核4G+4G swap)~220 tk/s</div> `elsa` cpu <div style="text-indent: 1em;font-size: 9pt"> Platinum(2C2G+4G swap)~120 tk/s 内存瓶颈</div> `Murasaki` cuda & cpu <div style="text-indent: 1em;font-size: 9pt">2080Ti~8000 tk/s \| 2600~800tk/s </div> | · 用文件内的 `os.environ["ARGOS_DEVICE_TYPE"] = "cuda"` 来指定用不用 cuda，这行一定要在 `import argostranslate` 之前 <br> · 切记不要在端口转发机上部署 `tcpc`，鉴于翻译句子长度不确定，可能会写爆 swap 导致 IO 阻塞使得整个系统瘫痪 <br> · 偶尔会导致机器蓝屏，记得时不时看一眼 <br> · 不要修改 CTranslate2 构造函数让 gpu 用半精度，否则一些形如西班牙语的包会翻译错误，得到没有意义的字符序列 |
| v4_helpers.py `lmdb_compact_migrate` | `Kaguya` 单进程 | sbd 过程中出现了 400GB 的 mdb 文件不够用的情况，经查发现文件利用率很低，需要手动做稠密拷贝生成一个更紧密的新 mdb 文件，然后再开大 MAP_SIZE 把工作继续做下去 |
| v4_helpers.py `lmdb_usage` | `Kaguya` 单进程 | 监控 mdb 文件的利用率，以便你知道什么时候该去调用 `lmdb_compact_migrate` |
| v4_tr_recover.py `gen_filewise` | `kuso` 单进程 | 生成文件级对齐 dataset, 确保你的磁盘空间足够，没什么坑直接跑就行 |
| v4_tr_recover.py `gen_sbd_dataset` | `kuso` 单进程 | 把放在 lmdb 的 sbd 缓存做成 dataset 传到 hf |
| v4_tr_recover.py `gen_tr_dataset` | `kuso` 单进程 | 把放在 lmdb 的机翻缓存做成 dataset 传到 hf |
| v4_tr_recover.py `gen_bilingual_align_consumer` | `kuso` 单进程 | 这步生成段落级双语对齐的语料。跟之前的所有语言对齐到英语不同，v4里改成了对于一对非英语语言，用他们的英翻来对齐。<br> 这步本来因为磁盘IO生产的任务吞吐量大于 lcs 对齐吞吐量，做了多进程处理，但因为对齐过程中偶尔会有超大文件，比如某些文件的 A 串有 271215 单词，B 串有 150423 单词，应用 `Hunt-Szymanski` 算法后得到总共匹配数有 `16242859187` 对，实际占用大约 `415.3GB` 的运行内存，所以后面改成单进程。因为这个内存问题甚至对23年写好的 `pylcs` 做了修改。内存瓶颈是一个前向链表数组 `linklistnode` ，它包括一个记B串下标的 `b_idx` ，因为我们的文件集中没有超过 4GB 的单文件，所以这个 B 串下标不可能超过 uint32，这个现在拆出来改成单独一个数组 `b_idx_arr` 用 uint32 来记，另一个数组 prv_arr 由于它是记上一个链表节点的下标，在两边单词数都是十万级别的情况下匹配数有可能会越界 uint32 所以保留了 int64。本想要进一步改为手写的48位整数再凹点，结果我手动给磁盘分了 700 个G的分页文件给操过去了。由于这个链表节点个数可以预测所以改成数组而不用vector，实际确实除了分页文件不够大报错了一次OOM阻塞后面任务执行，其它也没什么问题。因为这个太耗内存了，就搞了个缓存 align 函数的存盘文件把结果放到 lmdb 里。 |
| v4_tr_recover.py `gen_all_lang_align` | `kuso` 单进程 | 把双语种对齐用并查集搞一下做成全语种对齐。v4里由于双语种是 n^2 对齐了，可能产出的段落块会比老代码更大 |

# 比老管线强的地方

总的来说，从9月2号开始一边做实验一边跑，到11月4日正式跑完把数据上传，重写后的 v4 管线比之前有很大提升:
- 巨幅提高了翻译步骤显卡算力利用率，除去开发和调试时间之外，翻译步骤大部分负载都能够被单机消化，单卡 4070Ti 跑了两个星期就完成了老管线5个非英语语言每个跑一个星期，且算上借来的机器一共用了[约70个不同型号的有效核心](https://wiki.mnbvc.org/doku.php/%E5%A4%A7%E5%9E%8B%E6%9C%BA%E7%BF%BB%E4%BB%BB%E5%8A%A1%E5%88%86%E5%8F%91%E4%B8%8E%E9%83%A8%E7%BD%B2) 才能完成的任务
- 下载文件、导 docx 和翻译三个算力开销巨大的步骤流水线化，区别于老管线，无需等待上一步完全跑完，它改成了定期扫描目录，新的任务来了就继续处理的模式
- 缓存采用小粒度增量设计，使得跑新数据时老缓存仍然用得上，更新数据只需要爬新的，不需要完全重爬
- 时间范围更大，把2025年9月16号为止能下载到并且正常转出的所有 doc 文件都做完了，而不是只有 2000年1月-2023年8月的
- 文件级对齐数据量有 54.5GB，老管线是 45.3GB