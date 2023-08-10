# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import logging
import os
import sys

import fairseq
import torch
import torch.nn.functional as F
from fairseq.data.audio.audio_utils import get_features_or_waveform
from feature_utils import dump_feature
from feature_utils import get_path_iterator

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=os.environ.get("LOGLEVEL", "INFO").upper(),
    stream=sys.stdout, )
logger = logging.getLogger("dump_hubert_feature")


class HubertFeatureReader(object):
    def __init__(self, ckpt_path, layer, max_chunk=1600000):
        (model, cfg,
         task, ) = fairseq.checkpoint_utils.load_model_ensemble_and_task(
             [ckpt_path])
        self.model = model[0].eval().cuda()
        self.task = task
        self.layer = layer
        self.max_chunk = max_chunk
        logger.info(f"TASK CONFIG:\n{self.task.cfg}")
        logger.info(f" max_chunk = {self.max_chunk}")

    def read_audio(self, path, ref_len=None):
        wav = get_features_or_waveform(
            path, need_waveform=True, use_sample_rate=self.task.cfg.sample_rate)
        if wav.ndim == 2:
            wav = wav.mean(-1)
        assert wav.ndim == 1, wav.ndim
        if ref_len is not None and abs(ref_len - len(wav)) > 160:
            logging.warning(f"ref {ref_len} != read {len(wav)} ({path})")
        return wav

    def get_feats(self, path, ref_len=None):
        x = self.read_audio(path, ref_len=ref_len)
        with torch.no_grad():
            x = torch.from_numpy(x).float().cuda()
            if self.task.cfg.normalize:
                x = F.layer_norm(x, x.shape)
            x = x.view(1, -1)

            feat = []
            for start in range(0, x.size(1), self.max_chunk):
                x_chunk = x[:, start:start + self.max_chunk]
                feat_chunk, _ = self.model.extract_features(
                    source=x_chunk,
                    padding_mask=None,
                    mask=False,
                    output_layer=self.layer, )
                feat.append(feat_chunk)
        return torch.cat(feat, 1).squeeze(0)


def main(tsv_dir, split, ckpt_path, layer, nshard, rank, feat_dir, max_chunk):
    reader = HubertFeatureReader(ckpt_path, layer, max_chunk)
    generator, num = get_path_iterator(f"{tsv_dir}/{split}.tsv", nshard, rank)
    dump_feature(reader, generator, num, split, nshard, rank, feat_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--tsv_dir", default='../data/libritts_train_clean_360')
    parser.add_argument("--split", default="audio_files")
    parser.add_argument(
        "--ckpt_path", default='../hubert_checkpoint/hubert_base_ls960.pt')
    parser.add_argument("--layer", type=int, default=10)
    parser.add_argument("--nshard", type=int, default=5)
    parser.add_argument("--rank", type=int, default=0)
    parser.add_argument(
        "--feat_dir",
        default='../data/libritts_train_clean_360/semantic_feature')
    parser.add_argument("--max_chunk", type=int, default=1600000)
    args = parser.parse_args()
    logger.info(args)

    main(**vars(args))