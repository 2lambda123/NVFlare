# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from typing import Dict, Optional, Union

from nvflare.app_common.abstract.fl_model import FLModel
from nvflare.app_common.data_exchange.constants import ExchangeFormat
from nvflare.app_common.data_exchange.data_exchanger import DataExchangeException, DataExchanger
from nvflare.fuel.utils import fobs
from nvflare.fuel.utils.import_utils import optional_import
from nvflare.fuel.utils.pipe.file_pipe import FilePipe

from .config import ClientConfig, ConfigKey, from_file
from .constants import CONFIG_EXCHANGE
from .model_registry import ModelRegistry

PROCESS_MODEL_REGISTRY = None


def init(config: Union[str, Dict] = f"config/{CONFIG_EXCHANGE}", rank: Optional[str] = None):
    """Initializes NVFlare Client API environment.

    Args:
        config (str or dict): configuration file or config dictionary.
        rank (str): local rank of the process.
            It is only useful when the training script has multiple worker processes. (for example multi GPU)
    """
    global PROCESS_MODEL_REGISTRY  # Declare PROCESS_MODEL_REGISTRY as global

    try:
        if rank is None:
            rank = os.environ.get("RANK", "0")

        if PROCESS_MODEL_REGISTRY:
            raise RuntimeError("Can't call init twice.")

        if isinstance(config, str):
            client_config = from_file(config_file=config)
        elif isinstance(config, dict):
            client_config = ClientConfig(config=config)
        else:
            raise ValueError("config should be either a string or dictionary.")

        dx = None
        if rank == "0":
            if client_config.get_exchange_format() == ExchangeFormat.PYTORCH:
                tensor_decomposer, ok = optional_import(
                    module="nvflare.app_opt.pt.decomposers", name="TensorDecomposer"
                )
                if ok:
                    fobs.register(tensor_decomposer)
                else:
                    raise RuntimeError(f"Can't import TensorDecomposer for format: {ExchangeFormat.PYTORCH}")

            pipe_args = client_config.get_pipe_args()
            if client_config.get_pipe_class() == "FilePipe":
                pipe = FilePipe(**pipe_args)
            else:
                raise RuntimeError(f"Pipe class {client_config.get_pipe_class()} is not supported.")

            dx = DataExchanger(
                supported_topics=client_config.get_supported_topics(),
                pipe=pipe,
                pipe_name=client_config.get_pipe_name(),
            )

        PROCESS_MODEL_REGISTRY = ModelRegistry(client_config, rank, dx)
    except Exception as e:
        print(f"Exception {e} happens in flare.init()")


def _get_model_registry() -> ModelRegistry:
    if PROCESS_MODEL_REGISTRY is None:
        raise RuntimeError("needs to call init method first")
    return PROCESS_MODEL_REGISTRY


def receive(timeout: Optional[float] = None) -> Optional[FLModel]:
    """Receives model from NVFlare side.

    Returns:
        An FLModel received.
    """
    model_registry = _get_model_registry()
    return model_registry.get_model(timeout)


def send(fl_model: FLModel, clear_registry: bool = True) -> None:
    """Sends the model to NVFlare side.

    Args:
        fl_model (FLModel): Sends a FLModel object.
        clear_registry (bool): To clear the registry or not.
    """
    model_registry = _get_model_registry()
    model_registry.submit_model(model=fl_model)
    if clear_registry:
        clear()


def clear():
    """Clears the model registry."""
    model_registry = _get_model_registry()
    model_registry.clear()


def system_info() -> Dict:
    """Gets NVFlare system information.

    System information will be available after a valid FLModel is received.
    It does not retrieve information actively.

    Returns:
       A dict of system information.
    """
    model_registry = _get_model_registry()
    return model_registry.get_sys_info()


def get_config() -> Dict:
    model_registry = _get_model_registry()
    return model_registry.config.config


def get_job_id() -> str:
    sys_info = system_info()
    return sys_info.get(ConfigKey.JOB_ID, "")


def get_total_rounds() -> int:
    sys_info = system_info()
    return sys_info.get(ConfigKey.TOTAL_ROUNDS, 0)


def get_site_name() -> str:
    sys_info = system_info()
    return sys_info.get(ConfigKey.SITE_NAME, "")


def is_running() -> bool:
    try:
        receive()
        return True
    except DataExchangeException:
        return False


def is_train() -> bool:
    model_registry = _get_model_registry()
    if model_registry.rank != "0":
        raise RuntimeError("only rank 0 can call is_train!")
    return model_registry.task_name == model_registry.config.config[ConfigKey.TRAIN_TASK_NAME]


def is_evaluate() -> bool:
    model_registry = _get_model_registry()
    if model_registry.rank != "0":
        raise RuntimeError("only rank 0 can call is_evaluate!")
    return model_registry.task_name == model_registry.config.config[ConfigKey.EVAL_TASK_NAME]


def is_submit_model() -> bool:
    model_registry = _get_model_registry()
    if model_registry.rank != "0":
        raise RuntimeError("only rank 0 can call is_submit_model!")
    return model_registry.task_name == model_registry.config.config[ConfigKey.SUBMIT_MODEL_TASK_NAME]
