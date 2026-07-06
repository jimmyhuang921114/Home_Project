---
license: apache-2.0
language:
- en
pipeline_tag: zero-shot-image-classification
tags:
- image recognition
---

# Recognize Anything & Tag2Text

Model card for <a href="https://recognize-anything.github.io/">Recognize Anything Plus Model (RAM++) </a>.

RAM++ is the next generation of RAM, which can recognize any category with high accuracy, including both predefined common categories and diverse open-set categories.

RAM++ outperforms existing SOTA image fundamental reocngition models in terms of common tag categorie, uncommon tag categories, and  human-object interaction phrase.


## TL;DR

Authors from the [paper](https://arxiv.org/abs/2306.03514) write in the abstract:

*We introduce the Recognize Anything Plus Model (RAM++), a fundamental image recognition model with strong open-set recognition capabilities, by injecting semantic concepts into image tagging training framework. Previous approaches are either image tagging models constrained by limited semantics, or vision-language models with shallow interaction for suboptimal performance in multi-tag recognition. In contrast, RAM++ integrates image-text alignment and image-tagging within a unified fine-grained interaction framework based on image-tags-text triplets. This design enables RAM++ not only excel in identifying predefined categories, but also significantly augment the recognition ability in open-set categories. Moreover, RAM++ employs large language models~(LLMs) to generate diverse visual tag descriptions, pioneering the integration of LLM's knowledge into image tagging training. This approach empowers RAM++ to integrate visual description concepts for open-set recognition during inference. Evaluations on comprehensive image recognition benchmarks demonstrate RAM++ exceeds existing state-of-the-art (SOTA) fundamental image recognition models on most aspects. *


## BibTex and citation info

```


@article{zhang2023recognize,
  title={Recognize Anything: A Strong Image Tagging Model},
  author={Zhang, Youcai and Huang, Xinyu and Ma, Jinyu and Li, Zhaoyang and Luo, Zhaochuan and Xie, Yanchun and Qin, Yuzhuo and Luo, Tong and Li, Yaqian and Liu, Shilong and others},
  journal={arXiv preprint arXiv:2306.03514},
  year={2023}
}

@article{huang2023tag2text,

  title={Tag2Text: Guiding Vision-Language Model via Image Tagging},
  author={Huang, Xinyu and Zhang, Youcai and Ma, Jinyu and Tian, Weiwei and Feng, Rui and Zhang, Yuejie and Li, Yaqian and Guo, Yandong and Zhang, Lei},
  journal={arXiv preprint arXiv:2303.05657},
  year={2023}
}
```