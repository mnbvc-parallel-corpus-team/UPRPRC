# UPRPRC: Unified Pipeline for Reproducing Parallel Resources - Corpus from the United Nations

Read [README_CN.md](README_CN.md) for Chinese.

> In Natural Language Processing (NLP), the fidelity and accessibility of multilingual datasets are paramount for advancing machine translation (MT). We introduce a complete end-to-end solution: from data acquisition via web scraping to text alignment. To address the obsolescence of previous access methods, our novel pipeline includes a minimalist, single-machine runnable example and optional distributed computing steps. Building on previous efforts with advanced alignment tools, the corpus is presented with three levels of granularity up to the paragraph level, using the Hunt-Szymanski algorithm. Through the new approach, a parallel corpus can be generated that is currently the largest non-AI-generated one in the world. The corpus is readily accessible under the MIT License.

This repository hosts the complete data processing pipeline from the [MNBVC](https://github.com/esbatmop/MNBVC) Parallel Corpus Team. These scripts create a large-scale, six-language parallel corpus using documents from the [United Nations Digital Library](https://digitallibrary.un.org/).

Our end-to-end process includes:

1.  **Crawling** a list of documents by year.
2.  **Downloading** the source document files.
3.  **Converting** documents to text and generating a file-level aligned corpus.
4.  **Aligning** texts at the paragraph level to create bilingual corpora.
5.  **Merging** the bilingual alignments into a final multilingual, paragraph-block corpus.

Corpus produced by UPRPRC:

- [https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20230240](https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20230240)
- [https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20250102](https://huggingface.co/datasets/liwu/MNBVC/tree/main/parallel/united_nations/20250102)
- [https://huggingface.co/datasets/bot-yaya/rework_undl_text](https://huggingface.co/datasets/bot-yaya/rework_undl_text)
- [https://huggingface.co/datasets/bot-yaya/undl_ar2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_ar2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_de2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_de2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_es2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_es2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_fr2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_fr2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_ru2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_ru2en_aligned)
- [https://huggingface.co/datasets/bot-yaya/undl_zh2en_aligned](https://huggingface.co/datasets/bot-yaya/undl_zh2en_aligned)

New Corpus Run at 09/14/2025:

- [full file index crawl from UNDL website at 09/14/2025, sorted by publication date ascending](https://huggingface.co/datasets/bot-yaya/documents.un.org_search_result)
- [full pdf file crawl from UNDL website at 09/14/2025](https://huggingface.co/datasets/bot-yaya/UPRPRC_pdffiles_from_UN)
- [full doc file crawl from UNDL website at 09/14/2025](https://huggingface.co/datasets/bot-yaya/UPRPRC_docfiles_from_UN)
- [paragraph-level SBD sentence segmentation cache](https://huggingface.co/datasets/bot-yaya/UPRPRC_SBD_KV)
- [sentence-level machine translation cache](https://huggingface.co/datasets/bot-yaya/UPRPRC_TR_KV)
- [filewise fully aligned corpus exported from doc files](https://huggingface.co/datasets/bot-yaya/UPRPRC_FTXT_FILEWISE)
- [bilingual paragraph-level aligned corpus](https://huggingface.co/datasets/bot-yaya/UPRPRC_BILINGUAL)
- [paragraph-level all language fully aligned corpus](https://huggingface.co/datasets/bot-yaya/UPRPRC_BLOCKWISE)

## Overview

![Overview of UPRPRC](charts/flowchart.jpeg)

## Dependencies

We recommend using `Python 3.9+` over `Win10 21h2+`. `Office 2019` or newer must be installed.

```bash
cd scripts
pip install -r requirements.txt
```

### Standalone Workflow

This workflow is designed for users who want to run the entire pipeline on a single machine and are not primarily concerned with execution speed. The process involves running a sequence of Python scripts in the order defined in `scripts/new_sample_all.py`.

**1. Configuration**

Before running the scripts, you must configure the settings in `scripts/const.py`:

1.  Set `GET_LIST_FROM_YEAR` and `GET_LIST_TO_YEAR` to define the time range for the documents you want to crawl.
2.  You can modify `WORK_DIR` and other output paths, but we recommend keeping the default settings to ensure consistency.

> **Pro Tip:** We suggest setting `GET_LIST_FROM_YEAR` and `GET_LIST_TO_YEAR` to the same year and running the entire pipeline iteratively. This allows you to process the data in manageable annual batches.

**2. Execution Steps**

Navigate to the `scripts` directory and run the following commands in order:

```bash
cd scripts

# 1. Crawl the list of document symbols for the specified year range.
py new_sample_get_list.py

# 2. Asynchronously download the .doc files based on the list from the previous step.
py new_sample_get_doc_async_candidate.py

# 3. Convert .doc files to .txt and generate the file-level aligned corpus (filewise_result.jsonl).
py new_sample_doc2txt.py

# 4. Translate the non-English text files into English, paragraph by paragraph.
py new_sample_txt2translate.py

# 5. Align the translated paragraphs with the English text using the GAPA algorithm. 
#    This generates the bilingual, paragraph-level corpus as a Hugging Face Dataset.
py new_sample_translate2align.py

# 6. Merge the bilingual alignments into a fully aligned, six-language corpus (blockwise_result.jsonl).
py new_sample_align2mergedjsonl.py
```

### Performance Bottleneck and Distributed Solution

The machine translation step (`new_sample_txt2translate.py`) is by far the most time-consuming and computationally intensive part of the pipeline, accounting for approximately **99.1%** of the total execution time.

To address this bottleneck, we have developed a distributed solution. We highly recommend this approach for users with access to:
*   Multiple machines or servers.
*   Servers with multi-socket CPUs.
*   Machines with multiple GPUs.
*   Cloud computing resources (e.g., GCP, AWS, Colab Pro).

The distributed architecture consists of a central server that distributes translation tasks to multiple clients.

**Setup and Execution**

1.  **Deploy the Task Server**:
    On a server that is accessible to all clients, run the task distribution server:
    ```bash
    py new_sample_txt2translate_distrib_candidate_server.py
    ```
    *   **Networking**: Before starting, ensure the `TRANSLATION_SERVER_PORT` in `const.py` is correctly configured and matches the port in the client scripts. If your clients are not on the same local network, you will need a server with a public IP or a port-forwarding solution like [nps](https://github.com/ehang-io/nps).
    *   **Storage**: The server must have sufficient storage space. Intermediate translation files are saved as uncompressed `pickle` objects and can be large.

2.  **Run Client Workers**:
    On each machine with available computing resources, run the client script to receive and process translation tasks:
    ```bash
    py new_sample_txt2translate_distrib_candidate_client.py
    ```

**Tips for Optimizing Client Performance:**

*   **GPU Acceleration**: To use a GPU, uncomment the line `os.environ['ARGOS_DEVICE_TYPE'] = 'cuda'` in the client script. For multi-GPU systems, you can specify a device (e.g., `cuda:0`, `cuda:1`). Since `argostranslate` may not fully saturate a powerful GPU, you can often run a CPU-based client instance alongside a GPU instance on the same machine.

*   **Multi-CPU Servers**: For servers with multiple CPU sockets, launch one client instance per socket to maximize hardware utilization.

*   **Google Colab**: We provide `new_sample_txt2translate_distrib_candidate_client_for_colab.ipynb` for easy use in Google Colab. Free-tier users can typically run multiple notebooks simultaneously, so you can duplicate the file to run several clients in parallel.

*   **Cloud VM Deployment**: For quick deployment on cloud VMs (GCP, AWS, etc.) or even in a `cloud shell`, you can use the `new_sample_txt2translate_distrib_candidate_deploy_debian12.sh` script. This script helps automate setup and execution. Please review the script before running, as you may only need to use specific parts of it for your environment. For example, our recommended Google Cloud machine configurations can be found in the README of the [bot-yaya/undl_en2zh_translation](https://huggingface.co/datasets/bot-yaya/undl_en2zh_translation) dataset.

When every translation task is done, **DO NOT FORGET TO FINALLY RUN `new_sample_txt2translate.py` ONCE**, since it will convert the translation cache produced at client into dataset for next step processing.

## Corpus Analysis and Statistics

### Document Structure and Temporal Scoping

The core organizational unit within the UN Digital Library (UNDL) relevant to parallel text is the document **"symbol"** (e.g., `A/RES/77/1`). As detailed in the [official UN documentation](https://research.un.org/en/docs/symbols), a symbol uniquely identifies a specific document, such as a resolution, a meeting record, or a working paper. Conceptually, a symbol acts as a container for the same document rendered in the UN's six official languages: Arabic (ar), Chinese (zh), English (en), French (fr), Russian (ru), and Spanish (es). This structure provides a natural source of high-quality, parallel data. However, the presence of all six language versions for any given symbol is not guaranteed; some symbols may have missing files for one or more languages.

Our initial data acquisition strategy involved programmatically crawling the sitemap index provided by the [UNDL](https://digitallibrary.un.org/sitemap_index.xml.gz). From this sitemap, we extracted a comprehensive list of document symbols. To define the temporal scope of our corpus, we filtered these symbols based on their **Release Time**, a timestamp indicating when a specific language file was made public. The collection period was defined from **January 1, 2000, to August 5, 2023**.

A significant challenge arose during our project: the UNDL's online platform and its underlying APIs underwent a substantial overhaul. This revision made our original data acquisition method non-reproducible. Specifically, re-crawling based on **Release Time** became infeasible for several reasons:

*   **Attribute Granularity**: `Release Time` is a file-level attribute, not a symbol-level one. This means different language versions of the same document could have different release times, complicating consistent temporal filtering.
*   **API Instability**: The new search API required to fetch `Release Time` proved unreliable for large-scale crawling, frequently returning `HTTP 429 Too Many Requests` errors.
*   **Search Imprecision**: The search endpoint often yielded imprecise matches, making it difficult to reliably associate a timestamp with a unique symbol.

To ensure the integrity of our statistical analysis, we adopted a more stable temporal metric: **Publication Time**. This attribute is a consistent, symbol-level property and is reliably accessible via the revised UNDL API.

> **Important Clarification**: The corpus dataset itself was curated using the original **Release Time** filter. However, all statistical analyses and charts presented here were generated by re-crawling the **Publication Time** for all symbols within our collected dataset. This ensures that the analysis is based on a stable and reproducible metric.

### Corpus Granularity Distribution

We analyzed the distribution of paragraphs per document and tokens per paragraph. The cumulative distribution charts below show that approximately 50% of documents contain 40 or fewer paragraphs, while approximately 80% of documents contain 137 or fewer paragraphs. Furthermore, approximately 80% of paragraphs consist of 75 or fewer tokens.

<div align="center">
  <img src="./charts/para_distri.png" alt="Paragraph Distribution per Document" width="49%">
  <img src="./charts/token_distri.png" alt="Token Distribution per Paragraph" width="49%">
</div>
<p align="center"><em>Figure: Distributions of paragraph and token counts.</em></p>

<div align="center">
  <img src="./charts/para_cum.png" alt="Cumulative Paragraph Distribution" width="49%">
  <img src="./charts/token_cum.png" alt="Cumulative Token Distribution" width="49%">
</div>
<p align="center"><em>Figure: Cumulative distributions for paragraphs per document and tokens per paragraph.</em></p>

### Language Distribution and Temporal Trends

To provide a comprehensive profile of our corpus, we conducted a series of analyses focusing on data distribution across languages and the temporal evolution of the corpus from 2000 to 2023.

The chart below illustrates the total number of documents collected for each language. Beyond the six primary UN languages, our corpus also includes a small number of German documents.

<div align="center">
  <img src="./charts/file-lang.svg" alt="Number of Documents per Language">
    <p align="center"><em>Figure: Number of Documents per Language across the entire corpus (2000-2023).</em></p>
</div>

The following charts provide a chronological overview, showing the number of unique document symbols per year and the number of files per language over the years.

<table>
  <tr>
    <td align="center" width="50%">
      <img alt="Number of Unique Document Symbols per Year" src="./charts/symbol-year.svg" width="95%"><br>
      <p align="center"><em>Figure: Number of Unique Document Symbols per Year.</em></p>
    </td>
    <td align="center" width="50%">
      <img alt="Files per Language Over Years" src="./charts/file-lang-year.svg" width="95%"><br>
      <p align="center"><em>Figure: Files per Language Over Years.</em></p>
    </td>
  </tr>
</table>

For a more granular view of data volume, we measured the annual counts of characters, words, and paragraphs for each language.

<table>
  <tr>
    <td align="center" width="33%">
      <img alt="Total Characters per Language Over Years" src="./charts/char-lang-year.svg" width="95%"><br>
      <p align="center"><em>Figure: Total Characters per Language Over Years.</em></p>
    </td>
    <td align="center" width="33%">
      <img alt="Total Words per Language Over Years" src="./charts/word-lang-year.svg" width="95%"><br>
      <p align="center"><em>Figure: Total Words per Language Over Years.</em></p>
    </td>
    <td align="center" width="33%">
      <img alt="Total Paragraphs per Language Over Years" src="./charts/para-lang-year.svg" width="95%"><br>
      <p align="center"><em>Figure: Total Paragraphs per Language Over Years.</em></p>
    </td>
  </tr>
</table>

This analysis substantiates our rationale for selecting **paragraphs** as the alignment unit. Paragraph counts exhibit relative consistency across languages, and the segmentation criterion (two consecutive line breaks) is more straightforward than sentence-level alignment, which requires language-specific rules and complex anomaly handling.

### Data Completeness Analysis

A critical aspect of a real-world parallel corpus is its completeness. We define a *missing file* as an instance where a document symbol exists, but a file for a specific language was not available. The chart below quantifies this data sparsity, revealing that the 2015-2016 period had a higher incidence of missing files, particularly for Spanish and Russian.

<div align="center">
  <img src="./charts/miss-file.svg" alt="Missing File Counts per Year and Language">
    <p align="center"><em>Figure: Missing File Counts per Year and Language.</em></p>
</div>

### Lexical Analysis

To offer a preliminary insight into the corpus's content, we identified the top 50 most frequent words in each language after converting text to lowercase and removing all punctuation.

<div align="center">
  <img src="./charts/top_ar.svg" alt="Top 50 Words in Arabic" width="49%">
  <img src="./charts/top_en.svg" alt="Top 50 Words in English" width="49%">
</div>
<p align="center"><em>Figure: Top 50 Most Frequent Words for Arabic and English.</em></p>

<div align="center">
  <img src="./charts/top_es.svg" alt="Top 50 Words in Spanish" width="49%">
  <img src="./charts/top_fr.svg" alt="Top 50 Words in French" width="49%">
</div>
<p align="center"><em>Figure: Top 50 Most Frequent Words for Spanish and French.</em></p>

<div align="center">
  <img src="./charts/top_ru.svg" alt="Top 50 Words in Russian" width="49%">
  <img src="./charts/top_zh.svg" alt="Top 50 Words in Chinese" width="49%">
</div>
<p align="center"><em>Figure: Top 50 Most Frequent Words for Russian and Chinese.</em></p>

<div align="center">
  <img src="./charts/top_de.svg" alt="Top 50 Words in German">
</div>
<p align="center"><em>Figure: Top 50 Most Frequent Words for German.</em></p>

## License and Availability

This project, including the entire data processing pipeline, is released under the **MIT License**.

The collected dataset, spanning from 2000 to 2023, is publicly available on [Hugging Face at `bot-yaya/rework_undl_text`](https://huggingface.co/datasets/bot-yaya/rework_undl_text). We hope this fosters transparency, ease of access, and the promotion of linguistic diversity within the machine learning community.

## Data Table Processing Workflow

To systematically remove large, noisy tables from documents and convert them into clean inline text suitable for alignment algorithms, we developed a multi-stage Python pipeline.

The pipeline proceeds as follows:

1.  **Document Conversion**:
    Raw `.doc` files are first converted to `.docx` using Microsoft Word via COM automation, then to plain text via Pandoc (`pandoc -t plain --wrap=none`). The process includes automatic handling of Word dialogs (e.g., repair or security prompts) to ensure robustness.

2.  **Character Preprocessing**:
    Zero-width and format-control characters (e.g., U+200E, soft hyphens) are stripped from the text to guarantee accurate line-width calculations for table parsing.

3.  **Table Detection and Flattening**:
    We identify and flatten three common ASCII-based table styles:
    *   *Multiline tables with explicit splitters*: Recognized by identical dash lines (`-----`) marking the header, splitter, and footer.
    *   *Multiline tables without explicit splitters*: Similar to the above, but only top and bottom delimiters are present.
    *   *ASCII grid tables*: Bordered by `+---+` and vertical bars (`|`).

4.  **Recursive Replacement**:
    A main routine iteratively applies the detectors. All detected tables are replaced by inline text segments, where each table row becomes a single line of space-separated cell contents in row-major order.

5.  **Output Generation**:
    The flattened, table-free paragraphs are saved to a dedicated output directory, providing clean text for downstream multilingual alignment.

[This entire procedure](https://github.com/mnbvc-parallel-corpus-team/UPRPRC/blob/main/scripts/new_sample_doc2txt.py) effectively removes bulky table noise while preserving semantic content in a linearized form suitable for text-processing algorithms.
