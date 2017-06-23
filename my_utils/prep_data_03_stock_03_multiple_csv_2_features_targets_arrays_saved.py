# source from https://github.com/happynoom/DeepTrade_keras
"""
### workflow
- import read_csv_2_arrays to convert csv to arrays
- import extract_feature to convert arrays of OHLCV to features, targets arrays
- import bz_save_array to save large arrays
- set days for training, validation and testing
- create gobal variables for storing training, validation and testing features arrays and targets arrays
- create paths for storing those arrays above
- user selected indicators for converting OHLCV to
- dir_path for stock csv
- count number of csv to use for creating features array and target arrays
- loop through every csv to convert from csv to arrays OHLCV, to arrays features and targets, and concatenate features and targets of different csv files
"""

import os
from prep_data_03_stock_01_csv_2_objects_2_arrays_DOHLCV import read_csv_2_arrays
from prep_data_03_stock_02_OHLCV_arrays_2_features_targets_arrays import extract_feature
import numpy as np
from prep_data_98_funcs_save_load_large_arrays import bz_save_array

# set days for training, validation and testing
days_for_valid = 1000
days_for_test = 700 # number of test samples
input_shape = [30, 61]  # [length of time series, length of feature]
window = input_shape[0]

# create gobal variables for storing training, validation and testing features arrays and targets arrays
train_features = None
valid_targets = None
valid_features = None
train_targets = None
test_features = None
test_targets = None

# create paths for storing those arrays above
train_features_path = "/Users/Natsume/Downloads/DeepTrade_keras/features_targets_data/train_features_path"
valid_targets_path = "/Users/Natsume/Downloads/DeepTrade_keras/features_targets_data/valid_targets_path"
valid_features_path = "/Users/Natsume/Downloads/DeepTrade_keras/features_targets_data/valid_features_path"
train_targets_path = "/Users/Natsume/Downloads/DeepTrade_keras/features_targets_data/train_targets_path"
test_features_path = "/Users/Natsume/Downloads/DeepTrade_keras/features_targets_data/test_features_path"
test_targets_path = "/Users/Natsume/Downloads/DeepTrade_keras/features_targets_data/test_targets_path"

# user selected indicators for converting OHLCV to
user_indicators = ["ROCP", "OROCP", "HROCP", "LROCP", "MACD", "RSI", "VROCP", "BOLL", "MA", "VMA", "PRICE_VOLUME"]

# dir_path for stock csv
dataset_dir = "/Users/Natsume/Downloads/DeepTrade_keras/dataset"

# count number of csv to use for creating features array and target arrays
total_csv_combine = 1
current_num_csv = 0

# loop through every csv to convert from csv to arrays OHLCV, to arrays features and targets, and concatenate features and targets of different csv files
for filename in os.listdir(dataset_dir):
    if current_num_csv >= total_csv_combine:
	    break
	# 000001.csv must be the first file accessed by program
    if filename == '000001.csv':

	    print("processing file: " + filename)
	    filepath = dataset_dir + "/" + filename
	    _, _, opens, highs, lows, closes, volumes = read_csv_2_arrays(filepath)

	    moving_features, moving_targets = extract_feature(selector=user_indicators)


		# save test_set and train_set
		# valid_set: 1000 days
		# test_set: 700 days
		# train_set: 6434 - 1000 -700 days
	    print("feature extraction done, start writing to file...")
	    train_end_test_begin = moving_features.shape[0] - days_for_valid - days_for_test

	    train_features = moving_features[0:train_end_test_begin]
	    train_targets = moving_targets[0:train_end_test_begin]

	    valid_features = moving_features[train_end_test_begin:train_end_test_begin+days_for_valid]
	    valid_targets = moving_targets[train_end_test_begin:train_end_test_begin+days_for_valid]

	    test_features = moving_features[train_end_test_begin+days_for_valid:train_end_test_begin+days_for_valid+days_for_test]
	    test_targets = moving_targets[train_end_test_begin+days_for_valid:train_end_test_begin+days_for_valid+days_for_test]

    else:
	    print("processing file: " + filename)
	    filepath = dataset_dir + "/" + filename
	    _, _, opens, highs, lows, closes, volumes = read_csv_2_arrays(filepath)

	    moving_features, moving_targets = extract_feature(selector=user_indicators)

	    print("feature extraction done, start writing to file...")
	    train_end_test_begin = moving_features.shape[0] - days_for_valid - days_for_test

	    train_features_another = moving_features[0:train_end_test_begin]
	    train_targets_another = moving_targets[0:train_end_test_begin]

	    valid_features_another = moving_features[train_end_test_begin:train_end_test_begin+days_for_valid]
	    valid_targets_another = moving_targets[train_end_test_begin:train_end_test_begin+days_for_valid]

	    test_features_another = moving_features[train_end_test_begin+days_for_valid:train_end_test_begin+days_for_valid+days_for_test]
	    test_targets_another = moving_targets[train_end_test_begin+days_for_valid:train_end_test_begin+days_for_valid+days_for_test]

	    train_features = np.concatenate((train_features, train_features_another), axis = 0)
	    train_targets = np.concatenate((train_targets, train_targets_another), axis = 0)

	    valid_features = np.concatenate((valid_features, valid_features_another), axis = 0)
	    valid_targets = np.concatenate((valid_targets, valid_targets_another), axis = 0)

	    test_features = np.concatenate((test_features, test_features_another), axis = 0)
	    test_targets = np.concatenate((test_targets, test_targets_another), axis = 0)

    current_num_csv += 1

bz_save_array(train_features_path, train_features)
bz_save_array(train_targets_path, train_targets)
bz_save_array(valid_features_path, valid_features)
bz_save_array(valid_targets_path, valid_targets)
bz_save_array(test_features_path, test_features)
bz_save_array(test_targets_path, test_targets)