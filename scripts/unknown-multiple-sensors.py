import sys
from warnings import warn
from time import time
from os import path

import numpy as np
import pickle

sys.path.append('..')
from fsd import FeatureShiftDetector
from fsd.divergence import ModelKS, KnnKS, FisherDivergence
from fsd.models import GaussianDensity, Knn
from fsd._utils import marginal_attack, create_graphical_model, sim_copula_data,\
                       get_detection_metrics, get_localization_metrics, plot_confusion_matrix, get_confusion_tensor

# Experiment Parameters
n_samples = 1000  # The number of samples in p, q (thus n_samples_total = n_samples*2)
n_bootstrap_runs = 250
n_expectation = 30
n_neighbors = 100
n_attacks = 100
alpha = 0.05  # Significance level
a = 0.5
b = 0.5
sqrtn = 5   # = sqrt(n_dim)
n_dim = sqrtn * sqrtn
random_seed_list = [0, 1, 2]
mi_list = [0.2, 0.1, 0.05, 0.01]
graph_type_list = ['complete', 'grid', 'cycle', 'random']
experiment_list = ['MB-SM', 'MB-KS']
n_attacked_sensors_list = [2, 3, 4, 5]

experiment_results_dict = dict()  # the dictionary of results per experiment_graphtype_mi
for n_compromised in n_attacked_sensors_list:
    for experiment in experiment_list:
        for graph_type in graph_type_list:
            for mi in mi_list:
                localization_results_across_seeds = []
                detection_results_across_seeds = []
                test_time_list = []
                for random_seed in random_seed_list:
                    # Setting up specific experiment information
                    rng = np.random.RandomState(random_seed)
                    print(f'Starting: {experiment} on {graph_type} graph with {n_compromised} compromised sensors, ' +
                          f'{mi} MI, and {random_seed} as the random seed')
                    graph = create_graphical_model(sqrtn=sqrtn, kind=graph_type, target_mutual_information=mi,
                                                   random_seed=random_seed, target_idx='auto')
                    if experiment == 'MB-SM':
                        model = GaussianDensity()
                        statistic = FisherDivergence(model, n_expectation=n_expectation)
                    elif experiment == 'MB-KS':
                        model = GaussianDensity()
                        statistic = ModelKS(model, n_expectation=n_expectation)
                    # Localization results are [did attack happen, was it localized, the test score] for each feature
                    localization_results = np.zeros(shape=(n_dim, n_attacks*2, 3))
                    # Detection results are [did a shift happen, was it detected]
                    detection_results = np.zeros(shape=(n_attacks*2, 2))
                    # Setting up attack data
                    random_feature_idxs = np.zeros(shape=(n_attacks*2, n_compromised))
                    for i in range(n_attacks*2):
                        random_feature_idxs[i] = rng.choice(n_dim, size=n_compromised, replace=False)
                    for test_idx, features in enumerate(random_feature_idxs[:n_attacks]):
                        localization_results[features, test_idx, 0] = 1  # recording if attacks happen for each test
                        detection_results[test_idx, 0] = 1
                    # Setting up FeatureShiftDetector
                    fsd = FeatureShiftDetector(statistic, bootstrap_method='simple',
                                               n_bootstrap_samples=n_bootstrap_runs,
                                               significance_level=alpha, n_compromised=n_compromised)
                    # since we are using data always drawn from the same distribution we only need to fit once
                    X_boot, Y_boot = sim_copula_data(n_samples, n_samples, mean=np.zeros(shape=sqrtn ** 2),
                                           cov=graph['cov'], a=a, b=b, rng=rng)
                    fsd.fit(X_boot, Y_boot)  # sets the detection threshold for us.
                    # beginning testing
                    for test_idx in range(n_attacks*2):
                        X_test, Y_test = sim_copula_data(n_samples, n_samples, mean=np.zeros(shape=sqrtn**2),
                                               cov=graph['cov'], a=a, b=b, rng=rng)
                        start = time()  # does not start earlier so time for data generatation is not taken into account
                        if detection_results[test_idx, 0]:  # if attack
                            j_attacked = random_feature_idxs[test_idx]  # here j_attacked is a set of features
                            Y_test = marginal_attack(Y_test, j_attacked)
                        detection, attacked_features, scores = \
                            fsd.detect_and_localize(X_test, Y_test, random_state=rng, return_scores=True)
                        localization_results[:, test_idx, 2] = scores
                        detection_results[test_idx, 1] = detection
                        if detection:  # if a distribution shift is detected, record localization results
                            localization_results[attacked_features, test_idx, 1] = 1
                        test_time_list.append(time() - start)
                    # recording testing results for seed
                    localization_results_across_seeds.append(localization_results.copy())
                    detection_results_across_seeds.append(detection_results.copy())

                # recording time per test across seeds
                time_per_test = np.array(test_time_list).mean()
                print(f'Time per test: {time_per_test:.4f} sec')
                # recording detection results across seeds
                detection_results = np.concatenate(detection_results_across_seeds, axis=0)
                detection_metrics = get_detection_metrics(true_labels=detection_results[:, 0],
                                                       predicted_labels=detection_results[:, 1])
                print('Detection results:')
                print(f'Precision: {detection_metrics["precision"]:.3f};' +
                      f' Recall: {detection_metrics["recall"]:.3f}')
                # recording localization results across seeds
                localization_results = np.concatenate(localization_results_across_seeds, axis=1)  # combines seed results
                localization_metrics = get_localization_metrics(localization_results[:, :, 0],
                                                                localization_results[:, :, 1], n_dim=n_dim)
                print('Localization results:')
                print(f'Micro-precision: {localization_metrics["micro-precision"]:.3f};' +
                      f' Micro-recall: {localization_metrics["micro-recall"]:.3f}')
                # ploting detection confusion matrix
                plot_title = f'Detection for {experiment} on {graph_type} graph with {mi} MI'
                # Uncomment below if you would like a detection confusion matrix plotted for each experiment
                # plot_confusion_matrix(detection_metrics["confusion_matrix"],
                #                       title=plot_title, plot=True)  # plots cm
                # saving results
                experiment_results = {
                    'detection_results': detection_results,
                    'detection_metrics': detection_metrics,
                    'localization_results': localization_results,
                    'localization_metrics': localization_metrics,
                    'time': np.array(test_time_list)
                }
                experiment_name = f'{experiment}_{graph_type}_{mi}_with_{n_compromised}_attacked'
                experiment_results_dict[experiment_name] = experiment_results
                experiment_save_name = path.join('..', 'results', 'unknown-multiple-sensors-dict.pickle')
                pickle.dump(experiment_results_dict, open(experiment_save_name, 'wb'))
                print()
print('Fin!')
