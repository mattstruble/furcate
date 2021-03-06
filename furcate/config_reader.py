# Copyright (c) 2020 Matt Struble. All Rights Reserved.
#
# Use is subject to license terms.
#
# Author: Matt Struble
# Date: Nov. 18 2020
import copy
import json
import logging
import os
import random
import threading

import pandas as pd


class ConfigReader:
    """
    A class to read and handle configuration data.

    Attributes
    ----------
    filename: str
        Path to the configuration file in memory
    data: dict
        Dictionary of key value pairs processed from the configuration file
    meta_data: dict
        Dictionary exclusively containing the meta data from the configuration file.
    run_configs: List[dict]
        Every permutation of configuration generated from data.
    permutable_keys: Set[string]
        Every data key which was used in generating the run_configs.

    Methods
    -------
    gen_run_configs():
        Returns the run_configs and permutable_keys from the loaded configuration
    remove_completed_runs(run_dict):
        Removes the provided run_dict from the stored run_configs.
    """

    # Bare minimum configuration keys required to run a default training fork
    _REQUIRED_KEYS = ["data_name", "data_dir", "batch_size", "epochs"]
    logger = logging.getLogger(__name__)

    def __init__(self, filename):
        """
        Loads the provided file name and stores the preliminary data in self.data and self.meta_data.
        :param filename: Name of configuration file to load.
        :type filename: string
        """
        self.filename = filename
        self.data, self.meta_data = self._load_config(filename)
        self._load_defaults()

        self.run_configs = []
        self.permutable_keys = set()
        self._generated = False

    def gen_run_configs(self):
        """
        Breaks down the configuration into all the possible permutations, removes excluded_configs, and shuffles the
        remaining permutations.
        :return: All configuration permutations (list), Data keys that had multiple permutations (Set)
        :rtype: list, set
        """
        if not self._generated:
            self.run_configs = self._gen_run_configs(self.data)
            self._exclude_configs()
            random.shuffle(self.run_configs)
            self._generated = True

        return self.run_configs, self.permutable_keys

    def _load_defaults(self):
        """
        Loads furcate default data and meta data values, if they don't already exist in the loaded data.
        :return: None.
        """
        self.data.setdefault("train_prefix", self.data["data_name"] + ".train")
        self.data.setdefault("test_prefix", self.data["data_name"] + ".test")
        self.data.setdefault("valid_prefix", self.data["data_name"] + ".valid")

    def _validate_data(self, data, fname):
        for key in self._REQUIRED_KEYS:
            if key not in data.keys():
                raise ValueError(
                    "The configuration file '{}' does not contain the required key: {}".format(
                        fname, key
                    )
                )

    def _load_config(self, fname):
        """
        Loads the passed in json file name into a dictionary and validates that the required keys exist.
        :param fname: File name to load.
        :type fname: string
        :return: data (dict), meta_data (dict)
        :rtype: dict, dict
        """
        with open(fname) as f:
            data = json.load(f)

        self._validate_data(data, fname)

        default_fname = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "config", "default.config"
        )

        with open(default_fname, "r") as f:
            default_config = json.load(f)

        data = {**default_config, **data}

        return data, data["meta"]

    def _gen_config_permutations(self, index, config, enumerated_data):
        """
        Recursively iterates over the enumerated data dictionary and generates every permutation of data possible.
        :param index: Current index.
        :type index: int
        :param config: Current copy of the built configuration.
        :type config: dict
        :param enumerated_data: Dictionary of values with enumerated indexes.
        :type enumerated_data: dict
        :return: A list of dictionary permutations.
        :rtype: list
        """
        if index >= len(enumerated_data):
            return [config]

        key = enumerated_data[index]["key"]

        if isinstance(enumerated_data[index]["value"], list):
            self.permutable_keys.add(key)
            values = enumerated_data[index]["value"]
        else:
            values = [enumerated_data[index]["value"]]

        result = []
        for value in values:
            tmp = copy.deepcopy(config)
            tmp[key] = value
            result.extend(
                self._gen_config_permutations(index + 1, tmp, enumerated_data)
            )

        return result

    def _gen_run_configs(self, data):
        """
        Generates every permutation of the passed in data and stores the results in self.run_configs.
        :param data: Dictionary containing configurations where arrays are treated as permutable hyperparameters.
        :type data: dict
        :return: None.
        """
        enumerated_data = {}

        for index, (key, value) in enumerate(data.items()):
            enumerated_data[index] = {"key": key, "value": value}

        return self._gen_config_permutations(0, {}, enumerated_data)

    def remove_completed_runs(self, run_dict):
        """
        Removes any configurations matching the completed run_dict from the run_configs list. Ignores meta data.
        :param run_dict: Dictionary containing run configurations.
        :type run_dict: dict
        :return: None
        """
        self.gen_run_configs()

        for config in self.run_configs:
            match = True
            for key, value in config.items():
                if key not in ["meta"]:
                    if run_dict[key] != value:
                        match = False
                        break

            if match:
                self.logger.debug(
                    "Removing previous run [%s] from run_configs", str(config)
                )
                self.run_configs.remove(config)
                break

    def _exclude_configs(self):
        """
        Iterates over the configured "exclude_configs" and removes any matching configurations from the generated
        run configs.
        :return: None
        """
        exclude_configs = self.meta_data["exclude_configs"]
        if len(exclude_configs) > 0 and len(self.run_configs) > 1:
            to_remove = []
            for run_config in self.run_configs:
                matched = False
                for config in exclude_configs:
                    matched = True
                    for key, value in config.items():
                        if run_config[key] != value:
                            matched = False
                            break

                    if matched:
                        break

                if matched:
                    to_remove.append(run_config)

            if len(to_remove) > 0:
                self.logger.info(
                    "Excluding %d configs matching configured 'exclude_configs'",
                    len(to_remove),
                )
                for remove in to_remove:
                    self.run_configs.remove(remove)


class ConfigWatcher(threading.Thread):
    logger = logging.getLogger(__name__)

    def __init__(self, config_reader, refresh_rate=60):
        threading.Thread.__init__(self)
        self.setDaemon(True)

        self.config_path = config_reader.filename
        self.config_reader = config_reader
        self.refresh_rate = refresh_rate
        self.flagged = False

        self._remove_completed_runs()

        self._mtime = os.path.getmtime(self.config_path)
        self._running = False
        self._config_lock = threading.Lock()
        self._event = threading.Event()

    def run(self):
        self._running = True
        while self._running:
            self._event.wait(self.refresh_rate)

            if self._mtime != os.path.getmtime(self.config_path):
                self.logger.info(
                    "Detected change in %s, reloading configurations.", self.config_path
                )
                self._mtime = os.path.getmtime(self.config_path)

                with self._config_lock:
                    self.config_reader = ConfigReader(self.config_path)
                    self._remove_completed_runs()

                self.flagged = True

    def _remove_completed_runs(self):
        run_configs, _ = self.config_reader.gen_run_configs()
        log_dir = self.config_reader.data["log_dir"]

        if os.path.exists(os.path.join(log_dir, "run_data.csv")):
            df = pd.read_csv(os.path.join(log_dir, "run_data.csv"))
            self.logger.info(
                "Detected previous runs, removing %d configuration(s).", len(df)
            )
            for _, row in df.iterrows():
                run_dict = row.to_dict()
                self.config_reader.remove_completed_runs(run_dict)

    def reset_flagged(self):
        self.flagged = False

    def get_config_reader(self):
        with self._config_lock:
            config_reader = self.config_reader

        return config_reader

    def stop(self):
        self.logger.debug("Stopping ConfigUpdater")
        self._running = False
        self._event.set()
