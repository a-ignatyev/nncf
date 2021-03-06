"""
 Copyright (c) 2019-2020 Intel Corporation
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
      http://www.apache.org/licenses/LICENSE-2.0
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
"""

# pylint:disable=no-name-in-module
import os
import subprocess
import sys

import pytest

from nncf.torch import BKC_TORCH_VERSION
from tests.torch.helpers import Command
from tests.common.helpers import PROJECT_ROOT

TRANSFORMERS_COMMIT = "b0892fa0e8df02d683e05e625b3903209bff362d"
INSTALL_PATH = PROJECT_ROOT.parent
DATASET_PATH = os.path.join(PROJECT_ROOT, "tests", "torch", "data", "mock_datasets")


def create_command_line(args, venv, python=sys.executable, cuda_string=""):
    python_path = PROJECT_ROOT.as_posix()
    line = "PYTHONPATH={path} {venv_activate}; {cuda} {python_exe} {args}" \
        .format(path=python_path, venv_activate=venv, cuda=cuda_string, args=args, python_exe=python)
    return line


@pytest.fixture(autouse=True, scope="session")
def skip_tests(third_party):
    if not third_party:
        pytest.skip()


@pytest.fixture(scope="session")
def temp_folder(tmp_path_factory):
    return {"models": str(tmp_path_factory.mktemp("models", False)),
            "venv": str(tmp_path_factory.mktemp("venv", False))}


class CachedPipRunner:
    def __init__(self, venv_activation_script_path: str, cache_dir: str = None):
        self.venv_activate = venv_activation_script_path
        self.cache_dir = cache_dir

    def run_pip(self, pip_command: str, cwd: str = None, use_cache: bool = True):
        if not use_cache:
            cache_dir_entry = '--no-cache-dir'
        elif self.cache_dir is not None:
            cache_dir_entry = "--cache-dir {}".format(self.cache_dir)
        else:
            cache_dir_entry = ""
        subprocess.run(f"{self.venv_activate} && pip {cache_dir_entry} {pip_command}",
                       check=True, shell=True, cwd=cwd)

# pylint:disable=redefined-outer-name
class TestTransformers:
    @pytest.fixture(autouse=True)
    def setup(self, temp_folder):
        self.VENV_TRANS_PATH = str(os.path.join(temp_folder["venv"], "trans"))
        self.cuda_visible_string = "export CUDA_VISIBLE_DEVICES=0;"
        self.PATH_TO_PATCH = str(os.path.join(PROJECT_ROOT, "third_party_integration", "huggingface_transformers",
                                              "0001-Modifications-for-NNCF-usage.patch"))
        self.trans_python = str("{}/bin/python".format(self.VENV_TRANS_PATH))
        self.TRANS_PATH = str(os.path.join(self.VENV_TRANS_PATH, "transformers"))
        self.activate_venv = str(". {}/bin/activate".format(self.VENV_TRANS_PATH))

    @pytest.mark.dependency(name='install_trans')
    def test_install_trans_(self, pip_cache_dir):
        version_string = "{}.{}".format(sys.version_info[0], sys.version_info[1])
        subprocess.call("virtualenv -ppython{} {}".format(version_string, self.VENV_TRANS_PATH), shell=True)
        pip_runner = CachedPipRunner(self.activate_venv, pip_cache_dir)
        pip_runner.run_pip("uninstall setuptools -y")
        pip_runner.run_pip("install setuptools")
        pip_runner.run_pip("install torch=={}".format(BKC_TORCH_VERSION))
        subprocess.run("{} && git clone https://github.com/huggingface/transformers".format(self.activate_venv),
                       check=True, shell=True, cwd=self.VENV_TRANS_PATH)
        subprocess.run("{} && git checkout {}".format(self.activate_venv, TRANSFORMERS_COMMIT), check=True, shell=True,
                       cwd=self.TRANS_PATH)
        subprocess.run("{} && cp {} .".format(self.activate_venv, self.PATH_TO_PATCH), check=True, shell=True,
                       cwd=self.TRANS_PATH)
        subprocess.run("{} && git apply 0001-Modifications-for-NNCF-usage.patch".format(self.activate_venv),
                       check=True, shell=True, cwd=self.TRANS_PATH)
        pip_runner.run_pip("install .", cwd=self.TRANS_PATH)
        pip_runner.run_pip("install -e \".[testing]\"", cwd=self.TRANS_PATH)
        pip_runner.run_pip("install -r examples/requirements.txt", cwd=self.TRANS_PATH)
        pip_runner.run_pip("install boto3", cwd=self.TRANS_PATH)
        subprocess.run(
            "{} && {}/bin/python setup.py develop".format(self.activate_venv, self.VENV_TRANS_PATH), check=True,
            shell=True, cwd=PROJECT_ROOT)

    @pytest.mark.dependency(depends=['install_trans'], name='xnli_train')
    def test_xnli_train(self, temp_folder):
        com_line = "examples/text-classification/run_xnli.py --model_name_or_path bert-base-chinese" \
                   " --language zh --train_language zh --do_train --data_dir {} --per_gpu_train_batch_size 24" \
                   " --learning_rate 5e-5 --num_train_epochs 1.0 --max_seq_length 128 --output_dir {}" \
                   " --save_steps 200 --nncf_config nncf_bert_config_xnli.json" \
            .format(DATASET_PATH, os.path.join(temp_folder["models"], "xnli"))
        runner = Command(create_command_line(com_line, self.VENV_TRANS_PATH, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()
        assert os.path.exists(os.path.join(temp_folder["models"], "xnli", "pytorch_model.bin"))

    @pytest.mark.dependency(depends=['install_trans', 'xnli_train'])
    def test_xnli_eval(self, temp_folder):
        com_line = "examples/text-classification/run_xnli.py --model_name_or_path {output}" \
                   " --language zh --do_eval --data_dir {} --learning_rate 5e-5 --max_seq_length 128 --output_dir" \
                   " {output} --nncf_config nncf_bert_config_xnli.json --per_gpu_eval_batch_size 24" \
            .format(DATASET_PATH, output=os.path.join(temp_folder["models"], "xnli"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()

    @pytest.mark.dependency(depends=['install_trans'], name='squad_train')
    def test_squad_train(self, temp_folder):
        com_line = "examples/question-answering/run_squad.py --model_type bert --model_name_or_path " \
                   "bert-large-uncased-whole-word-masking-finetuned-squad --do_train --do_lower_case " \
                   "--train_file {}/squad/train-v1.1.json" \
                   " --learning_rate 3e-5 --num_train_epochs 1 --max_seq_length 384 --doc_stride 128 --output_dir " \
                   "{} --per_gpu_train_batch_size=1 --save_steps=200 --nncf_config" \
                   " nncf_bert_config_squad.json".format(DATASET_PATH, os.path.join(temp_folder["models"], "squad"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()
        assert os.path.exists(os.path.join(temp_folder["models"], "squad", "pytorch_model.bin"))

    @pytest.mark.dependency(depends=['install_trans', 'squad_train'])
    def test_squad_eval(self, temp_folder):
        com_line = "examples/question-answering/run_squad.py --model_type bert --model_name_or_path {output}" \
                   " --do_eval --do_lower_case  --predict_file {}/squad/dev-v1.1.json --learning_rate 3e-5" \
                   " --max_seq_length 384 --doc_stride 128 --per_gpu_eval_batch_size=4 --output_dir {output} " \
                   "--nncf_config nncf_bert_config_squad.json" \
            .format(DATASET_PATH, output=os.path.join(temp_folder["models"], "squad"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()

    @pytest.mark.dependency(depends=['install_trans'], name='glue_roberta_train')
    def test_glue_train(self, temp_folder):
        com_line = "examples/text-classification/run_glue.py --model_name_or_path" \
                   " roberta-large-mnli --task_name mnli --do_train --data_dir {}/glue/glue_data/MNLI" \
                   " --per_gpu_train_batch_size 4 --learning_rate 2e-5 --num_train_epochs 1.0 --max_seq_length 128 " \
                   "--output_dir {} --save_steps 200 --nncf_config" \
                   " nncf_roberta_config_mnli.json" \
            .format(DATASET_PATH, os.path.join(temp_folder["models"], "roberta_mnli"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()
        assert os.path.exists(os.path.join(temp_folder["models"], "roberta_mnli", "pytorch_model.bin"))

    @pytest.mark.dependency(depends=['install_trans', 'glue_roberta_train'])
    def test_glue_eval(self, temp_folder):
        com_line = "examples/text-classification/run_glue.py --model_name_or_path {output}" \
                   " --task_name mnli --do_eval --data_dir {}/glue/glue_data/MNLI --learning_rate 2e-5" \
                   " --num_train_epochs 1.0 --max_seq_length 128 --output_dir {output}" \
                   " --nncf_config nncf_roberta_config_mnli.json" \
            .format(DATASET_PATH, output=os.path.join(temp_folder["models"], "roberta_mnli"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()

    @pytest.mark.dependency(depends=['install_trans'], name='glue_distilbert_train')
    def test_glue_distilbert_train(self, temp_folder):
        com_line = "examples/text-classification/run_glue.py --model_name_or_path" \
                   " distilbert-base-uncased" \
                   " --task_name SST-2 --do_train --max_seq_length 128 --per_gpu_train_batch_size 8" \
                   " --data_dir {}/glue/glue_data/SST-2 --learning_rate 5e-5 --num_train_epochs 3.0" \
                   " --output_dir {} --save_steps 200 --nncf_config" \
                   " nncf_distilbert_config_sst2.json".format(DATASET_PATH, os.path.join(temp_folder["models"],
                                                                                         "distilbert_output"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()
        assert os.path.exists(os.path.join(temp_folder["models"], "distilbert_output", "pytorch_model.bin"))

    @pytest.mark.dependency(depends=['install_trans', 'glue_distilbert_train'])
    def test_glue_distilbert_eval(self, temp_folder):
        com_line = "examples/text-classification/run_glue.py --model_name_or_path {output}" \
                   " --task_name SST-2 --do_eval --max_seq_length 128" \
                   " --output_dir {output} --data_dir {}/glue/glue_data/SST-2" \
                   " --nncf_config nncf_distilbert_config_sst2.json" \
            .format(DATASET_PATH, output=os.path.join(temp_folder["models"], "distilbert_output"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()

    @pytest.mark.dependency(depends=['install_trans'], name='lm_train')
    def test_lm_train(self, temp_folder):
        com_line = "examples/language-modeling/run_language_modeling.py --model_type gpt2 --model_name_or_path gpt2" \
                   " --do_train --per_gpu_train_batch_size 8" \
                   " --train_data_file {}/wikitext-2-raw/wiki.train.raw " \
                   " --output_dir {} --nncf_config" \
                   " nncf_gpt2_config_wikitext_hw_config.json".format(DATASET_PATH, os.path.join(temp_folder["models"],
                                                                                                 "lm_output"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()
        assert os.path.exists(os.path.join(temp_folder["models"], "lm_output", "pytorch_model.bin"))

    @pytest.mark.dependency(depends=['install_trans', 'lm_train'])
    def test_lm_eval(self, temp_folder):
        com_line = "examples/language-modeling/run_language_modeling.py --model_type gpt2 " \
                   "--model_name_or_path {output} --do_eval " \
                   " --output_dir {output} --eval_data_file {}/wikitext-2-raw/wiki.train.raw" \
                   " --nncf_config nncf_gpt2_config_wikitext_hw_config.json" \
            .format(DATASET_PATH, output=os.path.join(temp_folder["models"], "lm_output"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()

    @pytest.mark.dependency(depends=['install_trans'])
    def test_convert_to_onnx(self, temp_folder):
        com_line = "examples/question-answering/run_squad.py --model_type bert --model_name_or_path {output}" \
                   " --output_dir {output}" \
                   " --to_onnx {output}/model.onnx".format(output=os.path.join(temp_folder["models"], "squad"))
        runner = Command(create_command_line(com_line, self.activate_venv, self.trans_python,
                                             self.cuda_visible_string), self.TRANS_PATH)
        runner.run()
        assert os.path.exists(os.path.join(temp_folder["models"], "squad", "model.onnx"))
