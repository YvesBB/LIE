"""
Copyright 2016 Deepgram

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

import os
import logging
import shutil
import math
import time
import traceback
import numpy
import tqdm
from ..providers import Provider
from ..utils import get_any_value, CriticalSection, parallelize, Timer
from ..loggers import PersistentLogger
from .hooks import TrainingHook

logger = logging.getLogger(__name__)
import numpy as np
import matplotlib.pyplot as plt
from ..utils import DisableLogging, idx
# with DisableLogging(): how to disable logging for a function
# if logger.isEnabledFor(logging.WARNING): work for pprint(object.__dict__)
# prepare examine tools
from pdb import set_trace
from pprint import pprint
from inspect import getdoc, getmembers, getsourcelines, getmodule, getfullargspec, getargvalues
# to write multiple lines inside pdb
# !import code; code.interact(local=vars())
###############################################################################
class RetryException(Exception):
	""" Exception class for retrying an operation on a new batch of data.
	"""
	pass

###############################################################################
class Executor:
	""" Class for using models.
	"""

	MAX_RETRIES = 3
	DEFAULT_RETRY_ENABLED = True
	NAN_IS_FATAL = True

	###########################################################################
	def __init__(self, model, loss=None, optimizer=None, auto_retry=None):
		""" Creates a new executor.

			# Arguments

			model: Model instance. The model to train.
			loss: Loss instance. The loss function to use in training/testing.
			optimizer: Optimizer instance. The optimizer to use in training.
		"""
		self.model = model
		self.loss = loss
		self.optimizer = optimizer

		if auto_retry is None:
			auto_retry = self.DEFAULT_RETRY_ENABLED
		self.auto_retry = auto_retry

	###########################################################################
	def compile(self, target=None, recompile=False, with_provider=None,
		**kwargs):
		""" Compiles a model.

			This generates a backend-specific representation of the model,
			suitable for training.

			# Arguments

			recompile: bool (default: False). If the model has already been
				compiled, it is not compiled again unless this flag is True.
			with_provider: Provider instance or None (default: None). If you
				want to merge the model's auxiliary data sources into your
				provider, you can specify the Provider instance here.

			# Return value

			None
		"""
		logger.warning("\n\nSelect a section to do compile() when section is not specified;\n\nSelect it based on Executor.loss|optimizer availability\n\n")
		if target is None:
			if self.loss is None and self.optimizer is None:
				target = 'evaluate'
			elif self.optimizer is None:
				target = 'test'
			else:
				target = 'train'

		logger.warning("\n\nDon't recompile if Executor.model.compiled is avaiable and the selected section is a key to Executor.model.compiled\n\n")
		if not recompile:
			if self.model.compiled is not None \
				and target in self.model.compiled:
				return

		logger.warning("\n\nMake sure model is built before compilation\n\n")
		if not self.model.is_built():
			logger.warning('This model has never been built before. We are '
				'going to try to build it now. But the model should always be '
				'built with Model.build() before trying to compile it, just '
				'to ensure that everything has been parsed as you expect.')
			if with_provider is not None:
				self.model.register_provider(with_provider)
			self.model.build()

		logger.warning('Compiling the model.')
		self.model.backend.compile(
			model=self.model,
			loss=self.loss if target != 'evaluate' else None,
			optimizer=None if target != 'train' else self.optimizer,
			blocking=True,
			**kwargs
		)

		if with_provider is not None:
			if isinstance(with_provider, Provider):
				self.model.supplement_provider(with_provider)
			elif isinstance(with_provider, dict):
				for provider in with_provider.values():
					self.model.supplement_provider(provider)
			else:
				raise ValueError('Unexpected provider type: {}'
					.format(with_provider))

	###########################################################################
	def test(self, providers, validating=False, hooks=None, step=False):
		""" Tests/validates the model on some data.

			# Arguments

			providers: dict. The keys are provider names, and the values are
				Provider instances. The data provider which serves the data to
				be evaluated on.
			validating: bool (default: False). If False, the console output
				refers to this process as "testing"; otherwise, it is referred
				to as "validating."

			# Return value

			The average loss across the validation set.
		"""

		self.compile('test', with_provider=providers)

		loss = {}
		counts = {}
		for k, provider in providers.items():
			n_entries, test_loss = self.test_with_provider(
				provider,
				name=k if len(providers) > 1 else None,
				validating=validating,
				hooks=hooks,
				step=step
			)
			#if 'total' not in test_loss:
			#	test_loss['total'] = sum(test_loss.values())
			loss[k] = test_loss
			counts[k] = n_entries

		total_count = sum(counts.values())
		average = {}
		for provider_name, loss_dict in loss.items():
			for branch_name, loss_value in loss_dict.items():
				weight = counts[provider_name] / total_count
				contribution = loss_value * weight
				if branch_name not in average:
					average[branch_name] = 0
				average[branch_name] += contribution

		if len(providers) > 1:
			logger.info(
				'Overall %s loss: %.3f',
				'validation' if validating else 'testing',
				sum(average.values())
			)

		return average, loss

	###########################################################################
	def test_with_provider(self, provider, *, name=None,
		validating=False, hooks=None, step=False):
		""" Tests/validates the model on a single provider.
		"""

		if validating:
			desc = ('Validating', 'Validation')
		else:
			desc = ('Testing', 'Test')

		# Create progress bar
		test_loss = None
		n_entries = 0
		first_batch = None
		test_func = self.retry(
			self.model.backend.test,
			self.auto_retry
		)
		with tqdm.tqdm(
					total=len(provider),
					unit='samples',
					desc='{}{}, loss=N/A'.format(
						desc[0],
						' "{}"'.format(name) if name else ''
					)
				) as pbar:

			# Present each batch to the network.
			for num_batches, batch in parallelize(enumerate(provider)):
				if step:
					self.do_step('Test', num_batches, batch)

				try:
					prediction, batch_loss = test_func(
						model=self.model,
						data=batch
					)
				except RetryException:
					continue

				if step and logger.isEnabledFor(logging.DEBUG):
					print(prediction)

				if first_batch is None:
					first_batch = (prediction, batch)

				batch_size = len(get_any_value(batch))

				#batch_loss = loss if isinstance(loss, float) \
				#	else sum(loss.values())

				new_entries = n_entries + batch_size

				if test_loss is None:
					test_loss = batch_loss
				else:
					test_loss = {
						k : v * (n_entries / new_entries) + \
							batch_loss[k] * (batch_size / new_entries)
						for k, v in test_loss.items()
					}
				#avg_loss = avg_loss * (n_entries / new_entries) + \
				#	batch_loss * (batch_size / new_entries)
				n_entries = new_entries

				# Update the progress bar
				pbar.set_description('{}{}, loss={:.3f}'.format(
					desc[0],
					' "{}"'.format(name) if name else '',
					sum(test_loss.values())
				))
				pbar.update(batch_size)

		if not n_entries:
			logger.warning('No data provided to validation/testing system.')
			return None

		logger.info('%s loss: %s%.3f',
			desc[1],
			'"{}"='.format(name) if name else '',
			sum(test_loss.values())
		)

		if hooks and first_batch is not None:
			prediction, batch = first_batch
			prev = first_batch
			for hook in hooks:
				new_prev = hook.apply(prev, first_batch, self.model)
				prev = (new_prev, prev[1]) \
					if not isinstance(new_prev, tuple) else new_prev

		return n_entries, test_loss

	###########################################################################
	def train(self, *args, last_weights=None, log=None, training_hooks=None,
		**kwargs):
		""" Trains the model on some data.

			This is the public entry point for training. It wraps the business
			logic so that it can handle error conditions.
		"""

		logger.critical("\n\nExecute and Dive into trainer.wrappered_trainer()\n\nReal and Actual Training starts now ... \n\n")
		print("""
		reason = 'unknown'
		try:
			result = self.wrapped_train(
				*args,
				log=log,
				training_hooks=training_hooks,
				**kwargs
			)
			# training actually takes place here ....
		""")

		reason = 'unknown'
		try:
			result = self.wrapped_train(
				*args,
				log=log,
				training_hooks=training_hooks,
				**kwargs
			)
		except (KeyboardInterrupt, Exception) as exc:
			logger.exception('Exception raised during training.')
			reason = traceback.format_exception_only(type(exc), exc)[0].strip()
			raise


		else:
			logger.critical("\n\nBoth else and finally blocks will be run even with return inside else \n\n")
			reason = 'success'
			return result
		finally:
			# save the last weights at the end of training after 2 epochs 6 batches in this case


			if last_weights is not None:
				logger.critical('\n\nself.model.save(last_weights) \n\nSaving most recent weights: %s\n\n', last_weights)

				# Protects critical code from system signals (e.g., keyboard interrupts)
				with CriticalSection():
					self.model.save(last_weights)
			if log is not None:
				log.flush()

			logger.critical("\n\nExecute training hooks\n\nEOF\n\n")
			print("""
			if training_hooks:
				for hook in training_hooks:
					hook.notify(
						TrainingHook.TRAINING_END,
						log=log,
						info={'Reason' : reason}
					)
			""")
			if training_hooks:
				for hook in training_hooks:
					hook.notify(
						TrainingHook.TRAINING_END,
						log=log,
						info={'Reason' : reason}
					)

	###########################################################################
	def wrapped_train(self, provider, *, validation=None, stop_when=None,
		log=None, best_train=None, best_valid=None, training_hooks=None,
		validation_hooks=None, checkpoint=None, step=False):
		""" Trains the model on some data.

			# Arguments

			provider: Provider instance. The data provider which serves the
				data to be trained on.
			validation: Provider instance or None (default: None). The data
				provider which serves validation data.
			stop_when: dict or None (default: None). Stopping criteria.
			log: Log instance or None (default: None). The logger to save
				training statistics with.

			# Return value

			None
		"""
		logger.critical("\n\nPrepare a number of functions\n\n")
		#######################################################################
		def run_validation(num_batches=None):
			""" Executes a validation run.
			"""
			logger.critical("\n\nResume timer for validate\n\nTest or validate on a validate provider: \n1. get average loss on validation\n2. get current validation loss\n3.update progress bar for validate\n\n4. save current validation weight to best_valid folder, if current validation loss is less than previous best validation loss\n\nLog training statistics after a validation run.\n\n")

			# validation is a data provider dict for validation
			if validation is None:
				return None

			nonlocal best_valid_loss

			# resume timer for validate
			timers['validate'].resume()

			# Continue with a validation run.
			previous_num_batches = {}
			try:
				# num_batches is not the same with num_batches of validation data provider
				if num_batches is not None:
					for provider in validation.values():
						if hasattr(provider, 'num_batches'):
							previous_num_batches[id(provider)] = \
								provider.num_batches
							provider.num_batches = num_batches

				# Tests/validates the model on some data.
				# output average_loss on validation and current loss on validation
				# update progress bar on validation
				average_loss, validation_loss = self.test(
					providers=validation,
					validating=True, # this is validating not testing
					hooks=validation_hooks
				)

			finally:
				if num_batches is not None:
					for provider in validation.values():
						if hasattr(provider, 'num_batches'):
							provider.num_batches = \
								previous_num_batches[id(provider)]

			if validation_loss is None:
				timers['validate'].pause()
				return None

			# a method to get dict.values() into pure number
			cur_validation_loss = sum(average_loss.values())
			# set None as a dict key
			validation_loss[None] = average_loss

			logger.critical("\n\nCurrent validation loss (average of validation loss in this validation run): %.3f\n\n", cur_validation_loss)

			# Save best historical validate weights, if condition met
			if best_valid is not None:
				if best_valid_loss is None or \
						cur_validation_loss < best_valid_loss:
					logger.critical(
						'\n\nSaving best historical validation weights: %s\n\n',
						best_valid
					)
					best_valid_loss = cur_validation_loss
					save_or_copy_weights(best_valid)
				else:
					logger.critical("\n\nDon't save current weights to best_valid weights folder, because\n\ncur_validation_loss < best_valid_loss: %s", cur_validation_loss < best_valid_loss)

			# update log validation info
			if log is not None:
				# Log training statistics after a validation run.
				log.log_validation(validation_loss, 'loss', clocks=timers)

			# pause timer for validate
			timers['validate'].pause()

			# return validation loss
			return validation_loss

		#######################################################################
		def save_or_copy_weights(target):
			""" Saves the current model weights.
			"""
			# save weights at the end of an epoch
			nonlocal saved_recent

			if saved_recent is None:

				with CriticalSection():
					self.model.save(target)
				saved_recent = target
				logger.critical("\n\nGiven no weights yet saved in this time of training, Set saved_recent from None to %s, \n\nand save weights using `self.model.save(target)`\n\n", target)
			elif not os.path.exists(saved_recent):
				logger.critical('\n\nRecently saved weight file seems to have '
					'vanished: %s\n\n', saved_recent)
				saved_recent = None
				save_or_copy_weights(target)
			elif os.path.exists(target) and \
					os.path.samefile(target, saved_recent):
				logger.critical('\n\nRecent weight file seems the same as the '
					'soon-to-be-saved file. Skipping: %s\n\n', target)
			else:
				logger.critical('\n\nGiven weights have saved previously, and previous saved folder is different from this folder for saving\n\nCopying weights from: %s\n\nValidation is new on its data, the weights are from best_train\n\n', saved_recent)
				with CriticalSection():

					# Recursively delete a directory tree.
					shutil.rmtree(target, ignore_errors=True)
					# Recursively copy a directory tree.
					shutil.copytree(saved_recent, target)

		#######################################################################
		def run_posttrain(n_entries, train_loss):
			""" Calculates training loss and saves if necessary.

				Read-only non-locals:
					n_entries, train_loss, best_train, log
				Read-write non-locals:
					best_train_loss
			"""
			logger.critical("\n\nGet the current training loss; \n\nIf there is no best_train_loss previously, or If current_train_loss < best_train_loss so far, \n\nSave current weights as best historical training weights\n\n")
			nonlocal best_train_loss
			if not n_entries:
				logger.warning('No data provided to training loop.')
				return None

			cur_train_loss = sum(train_loss.values())
			logger.critical('\n\nCurrent Training loss: %.3f\n\n', cur_train_loss)

			if best_train is not None:
				if best_train_loss is None or \
					cur_train_loss < best_train_loss:

					logger.critical('\n\nSaving best historical training weights: '
						'%s\n\n', best_train)
					best_train_loss = cur_train_loss
					save_or_copy_weights(best_train)
				else:
					if logger.isEnabledFor(logging.CRITICAL):
						print("\n\nDon't save current training weights to best_train_weights folder, because \n\ncur_train_loss < best_train_loss: {}\n\n".format(cur_train_loss < best_train_loss))

			if log is not None:
				log.log_training(train_loss, 'loss', clocks=timers)

			return cur_train_loss

		#######################################################################
		def run_training_hooks(cur_train_loss, validation_loss, status):
			""" Executes the training hooks, if necessary.

				Read-only non-locals:
					training_hooks, epoch, epochs, validation_loss
			"""
			if not training_hooks:
				return
			info = {
				'epoch' : epoch+1,
				'total_epochs' : epochs,
				'Training loss' : cur_train_loss
			}
			if validation is not None:
				info['Validation loss'] = validation_loss
			for hook in training_hooks:
				hook.notify(
					status,
					log=log,
					info=info
				)

		#######################################################################
		def write_time(title, seconds):
			""" Pretty-prints a number of seconds.
			"""
			seconds = int(seconds)
			minutes, seconds = divmod(seconds, 60)
			hours, minutes = divmod(minutes, 60)
			tqdm.tqdm.write('{}: {:02d}h {:02d}m {:02d}s'.format(
				title, hours, minutes, seconds
			))

		#######################################################################
		def print_times():
			""" Prints the current timer values.
			"""
			write_time('     Total wall-clock time', timers['all'].get())
			write_time('  Training wall-clock time', timers['train'].get())
			if validation is not None:
				write_time('Validation wall-clock time',
					timers['validate'].get())
			write_time('     Batch wall-clock time', timers['batch'].get())

		#######################################################################
		def run_checkpoint(*triggers, allow_validation=True):
			""" Runs the checkpoint triggers, if necessary.
			"""
			nonlocal last_checkpoint

			if checkpoint is None:
				return False

			timers['train'].pause()
			for k in triggers:
				if k not in checkpoint:
					continue
				if session[k] - last_checkpoint[k] >= checkpoint[k]:
					# We need a checkpoint

					# Save the file if necessary.
					if checkpoint['path']:
						tqdm.tqdm.write('Checkpoint...')
						logger.debug('Making checkpoint backup: %s',
							checkpoint['path'])
						save_or_copy_weights(checkpoint['path'])

					# Validate if necessary.
					if checkpoint.get('validation', False) \
							and allow_validation:
						if isinstance(checkpoint['validation'], bool):
							num_batches = None
						else:
							num_batches = checkpoint['validation']
						val_loss = run_validation(num_batches)
						run_training_hooks(None, val_loss,
							TrainingHook.VALIDATION_END)

					last_checkpoint = session.copy()

					timers['train'].resume()
					return True

			timers['train'].resume()
			return False

		#######################################################################
		# Create the timers
		logger.critical("\n\nCreate a dict of 4 timers: batch, train, validate, all\n\n")
		print("""
		timers = {
			'batch' : Timer(started=False),
			'train' : Timer(started=False),
			'validate' : Timer(started=False),
			'all' : Timer(started=False)
		}
		""")
		timers = {
			'batch' : Timer(started=False),
			'train' : Timer(started=False),
			'validate' : Timer(started=False),
			'all' : Timer(started=False)
		}

		#######################################################################
		logger.critical("\n\nMake sure Checkpoint's values in the right format\n\n")
		print("""
	  checkpoint:
	    path: cifar-checkpoint/
	    batches: 10
	    samples: 1000
	    minutes: (int) or remove this item
	    epochs: (int) or remove this item
		""")
		# Process checkpoint requirements
		if isinstance(checkpoint, dict):
			if 'path' not in checkpoint:
				checkpoint['path'] = 'checkpoint'

			found = False
			for k in ('epochs', 'batches', 'samples', 'minutes'):
				if k in checkpoint:
					if not isinstance(checkpoint[k], int):
						raise ValueError('Expected "{}" key in "checkpoint" '
							'to be an integer. Received: {}'.format(k,
							checkpoint[k]))
					found = True

			if not found:
				checkpoint['epochs'] = 1

		elif isinstance(checkpoint, str):
			checkpoint = {
				'path' : checkpoint,
				'epochs' : 1
			}
		elif checkpoint is not None:
			raise ValueError('Unknown format for "checkpoint". Expected a '
				'single file or a dictionary. Instead we received: {}'
				.format(checkpoint))

		#######################################################################
		logger.critical("\n\nIf log is not available, there is no best or any historical train loss or validate loss;\n\nIf log is available with files, then we can print out best historical train_loss and validate_loss;\n\n`best_train_loss = log.get_best_training_loss()`\n\n`best_valid_loss = log.get_best_validation_loss()` ")
		# Parse logs
		if log is None:
			logger.critical('\n\nNo log specified, so no historical loss information '
				'is available.\n\n')
			best_train_loss = best_valid_loss = None
		elif not isinstance(log, PersistentLogger):
			logger.critical('Log type is non-persistent, so no historical loss '
				'information is available.')
			best_train_loss = best_valid_loss = None
		else:
			best_train_loss = log.get_best_training_loss()
			if best_train_loss is not None:
				logger.critical('\n\nBest historical training loss: %.3f\n\n',
					best_train_loss)
			else:
				logger.critical('\n\nNo historical training loss available from logs.\n\n')

			best_valid_loss = log.get_best_validation_loss()
			if best_valid_loss is not None:
				logger.critical('\n\nBest historical validation loss: %.3f\n\n',
					best_valid_loss)
			else:
				logger.critical(
					'\n\nNo historical validation loss available from logs.\n\n')

			logger.critical("\n\nprint out wall clock time\n\nNo idea what are these??\n\n")
			clocks = log.get_clocks()
			if clocks:
				for k, v in clocks.items():
					if k in timers:
						timers[k].reset(v)
				print_times()



		#######################################################################
		logger.critical("\n\nget previous trained epochs number from log as log tracks history\n\ncompleted_epochs = log.get_number_of_epochs() if log else 0\n\n")
		# Parse desired number of epochs
		completed_epochs = log.get_number_of_epochs() if log else 0
		if not completed_epochs:
			logger.critical('No previous epochs.')
		else:
			logger.critical('\n\nRestarting from epoch %d.\n\n', completed_epochs+1)

		#######################################################################
		# Parse the stopping criterion mode.
		logger.critical("\n\nExtract mode\n\nThere are two valid modes: additional (default), total; \n\nIf mode is set total, then log must be available, otherwise, mode set back to additional automatically\n\n")
		if logger.isEnabledFor(logging.CRITICAL):
			print("""
			mode = stop_when.get('mode', valid_modes[0])
			""")
		valid_modes = ('additional', 'total')
		mode = stop_when.get('mode', valid_modes[0])

		if mode not in valid_modes:
			raise ValueError('"mode" in "stop_when" must be one of: {}. '
				'Instead, we received: {}.'.format(', '.join(valid_modes),
				mode))

		if mode == 'total' and log is None:
			logger.critical('The epoch specification has "mode" set to "%s". '
			'This mode requires a log to be used correctly. Kur will proceed '
			'as if "mode" were "%s".', mode, valid_modes[0])
			mode = valid_modes[0]
		if logger.isEnabledFor(logging.CRITICAL):
			print("mode: {}\n\n".format(mode))

		#######################################################################
		logger.critical("\n\nWhen to stop training based on epochs \n\nSet epochs to None if meant to be infinite\n\nepochs must be int or None;\n\nAccumulate epochs in additional mode; \n\nIn total mode, epochs == total epochs, stop training when completed_epochs>epochs\n\n")
		print("""
		epochs = stop_when.get('epochs')
		if epochs in ('inf', 'all', 'infinite', 'infinity'):
			epochs = None

		if not isinstance(epochs, (int, type(None))):
			raise ValueError('Expected "epochs" to be a None or aninteger. '
				'Instead, we received: {}.'.format(epochs))

		if epochs is not None:
			if mode == 'additional':
				epochs += completed_epochs
			if completed_epochs >= epochs:
				print('Epoch stopping-criterion met.')
				return
		""")
		# Parse "epoch" stopping criterion.

		epochs = stop_when.get('epochs')
		if epochs in ('inf', 'all', 'infinite', 'infinity'):
			epochs = None

		if not isinstance(epochs, (int, type(None))):
			raise ValueError('Expected "epochs" to be a None or aninteger. '
				'Instead, we received: {}.'.format(epochs))

		if epochs is not None:
			if mode == 'additional':
				epochs += completed_epochs
			if completed_epochs >= epochs:
				print('Epoch stopping-criterion met.')
				return

		#######################################################################
		logger.critical("\n\nExtract clock setting from stop_when,\nclock = stop_when.get('elapsed')\n\nExtract time_keeper (timer object), \ntime_keeper = clock.get('clock', default_time_keeper)\n\nCalc time for training, \nclock_time += clock[value] * multiplier\n\n")
		# Parse "elapsed" stopping criterion.

		default_time_keeper = 'all'
		clock = stop_when.get('elapsed')
		if isinstance(clock, dict):
			time_keeper = clock.get('clock', default_time_keeper)
			if time_keeper not in timers:
				raise ValueError('Invalid value for '
					'"stop_when.elapsed.clock". Must be one of: {}. Received: '
					'{}'.format(', '.join(timers), time_keeper))
			clock_time = 0
			for multiplier, value in (
				(1, 'minutes'), (60, 'hours'), (1440, 'days')
			):
				if value not in clock or not clock[value]:
					continue
				if not isinstance(clock[value], (int, float)):
					raise ValueError('Invalid value for "stop_when.clock.{}": '
						'{}'.format(value, clock[value]))
				clock_time += clock[value] * multiplier

		elif isinstance(clock, (int, float)):
			clock_time = clock  # Defaults to minutes.
			time_keeper = 'default_time_keeper'
		elif isinstance(clock, str) and clock in \
			('inf', 'all', 'infinite', 'infinity'):
			clock = None
		elif clock:
			raise ValueError('Invalid value for "stop_when.elapsed". Should '
				'be a dictionary or numeric. Received: {}'.format(clock))

		if clock:
			if clock_time <= 0:
				raise ValueError('"stop_when.elapsed" resolved to a '
					'non-positive value: {}'.format(clock_time))

			logger.critical("\n\nWhen to stop training based on the time spend on training\n\nIf mode is additional, update clock['mark'] as the starting time for training, \nclock['mark'] += clock['timer']();\n\nIf mode is total, then clock['seconds'] is the total time for training\n\nIf (clock['timer']() - clock['mark']) > clock['seconds'], in other words, previous training time is greater than total_training_time defined here, then Elapsed-time stopping criterion met.")
			print("""
		clock = {
			'seconds' : clock_time*60,
			'timer' : timers[time_keeper],
			'mark' : 0
		}

		if mode == 'additional':
			clock['mark'] += clock['timer']()

		if (clock['timer']() - clock['mark']) > clock['seconds']:
			print('Elapsed-time stopping criterion met.')
			return
			""")
			clock = {
				'seconds' : clock_time*60,
				'timer' : timers[time_keeper],
				'mark' : 0
			}

			if mode == 'additional':
				clock['mark'] += clock['timer']()

			if (clock['timer']() - clock['mark']) > clock['seconds']:
				print('Elapsed-time stopping criterion met.')
				return

		#######################################################################
		logger.critical("\n\nCreate a session dict\n\nAssign it to last_checkpoint\n\nCreate a train_func to Retry keras_backend.train() 3 times at most\n\nDive into keras_backend.train later???on logger.warning\n\n")
		print("""
		saved_recent = None

		session = {
			'epochs' : 0,
			'batches' : 0,
			'samples' : 0,
			'minutes' : time.perf_counter() / 60
		}
		last_checkpoint = session.copy()

		epoch = completed_epochs - 1
		train_func = self.retry(
			self.model.backend.train,
			self.auto_retry
		)
		""")
		saved_recent = None

		session = {
			'epochs' : 0,
			'batches' : 0,
			'samples' : 0,
			'minutes' : time.perf_counter() / 60
		}
		last_checkpoint = session.copy()

		epoch = completed_epochs - 1
		train_func = self.retry(
			self.model.backend.train,
			self.auto_retry
		)

		#######################################################################
		# Prepare to train
		logger.critical("\n\nCompile the trainer (Executor)\n\nPrints debug information about the sources in this provider\n\nExecute training hooks: does it actually do anything???\n\n")
		print("""
		self.compile('train', with_provider=provider)
		provider.source_shapes()

		if training_hooks:
			for hook in training_hooks:
				hook.notify(
					TrainingHook.TRAINING_START,
					log=log
				)

		all_done = False
		""")
		# compile() involve run_batch on 2 samples ???
		self.compile('train', with_provider=provider)
		provider.source_shapes()

		if training_hooks:
			for hook in training_hooks:
				hook.notify(
					TrainingHook.TRAINING_START,
					log=log
				)

		all_done = False

		#######################################################################
		# Main training loop.
		logger.critical("\n\nKeep training until all_done is set True or just return: \n\nResume timer using `timers['all'].resume()`\nand there is no timers['all'].pause() later\n\ncount epoch, and stop looping when total_num_epochs reached; \n\n")
		print("""
		timers['all'].resume()
		while not all_done:
			epoch += 1
			if epochs is not None and epoch >= epochs:
				print('Completed {} epochs.'.format(epochs))
				break

			print()
		""")
		timers['all'].resume()
		while not all_done:
			epoch += 1
			if epochs is not None and epoch >= epochs:
				print('Completed {} epochs.'.format(epochs))
				break

			print()

			###################################################################
			logger.critical("\n\nStart training an epoch:\n\nResume timer for train\ntimers['train'].resume()\n\n")
			timers['train'].resume()

			logger.critical("\n\nCreate progress bar:\n\n")
			train_loss = None
			n_entries = 0
			with tqdm.tqdm(
						total=len(provider),
						unit='samples',
						desc='Epoch {}/{}, loss=N/A'
							.format(epoch+1, epochs or 'inf')
					) as pbar:


				logger.critical("\n\nUnder the progress bar: Present each batch to the network\n\n")
				for num_batches, batch in parallelize(enumerate(provider)):

					# The loss averaged over this batch.
					logger.warning('Training on batch...')
					logger.critical("\n\nTurn on step feature if required \n\n")
					if step:
						self.do_step(
							'Train, Epoch {}'.format(session['epochs']+1),
							num_batches, batch)

					logger.critical("\n\nResume timer for batch\ntimers['batch'].resume()\n\nCalc prediction and batch_loss for this batch of data\nprediction, batch_loss = train_func(model=self.model, data=batch)\n\nDive into train_func(), \nthen into keras_backend.train(), \nthen into keras_backend.run_batch\n\n")

					timers['batch'].resume()
					try:
						prediction, batch_loss = train_func(
							model=self.model, data=batch)
					except RetryException:
						continue
					finally:
						logger.critical("\n\nThen pause timer for batch\n\n")
						timers['batch'].pause()

					if step and logger.isEnabledFor(logging.WARNING):
						print(prediction)

					# We just modified the weights. Invalidate the name of the
					# last weight file.
					saved_recent = None

					logger.warning('Finished training on batch.')

					# How many entries we just processed.
					batch_size = len(get_any_value(batch))

					logger.critical("\n\nlog training information after a batch\nlog.log_batch(batch_size, batch_loss, 'loss',clocks=timers)\n\nupdate session\n\nupdate Checkpoint: if condition?? satifised, then Prints the current(wall) timer values.\nif run_checkpoint('samples', 'batches', 'minutes',allow_validation=True):print_times()\n\nupdate new entries\n\n")
					if log is not None:
						log.log_batch(batch_size, batch_loss, 'loss',
							clocks=timers)

					# Update our session statistics.
					session['batches'] += 1
					session['samples'] += batch_size
					session['minutes'] = time.perf_counter() / 60

					# Checkpoint if necessary
					if run_checkpoint('samples', 'batches', 'minutes',
						allow_validation=True):
						print_times()

					# How many entries we've processed this epoch.
					new_entries = n_entries + batch_size

					logger.critical("\n\nGet average train_loss for each batch\n\n")
					print("""
		if train_loss is None:
			train_loss = batch_loss
		else:
			train_loss = {
				k : v * (n_entries / new_entries) + batch_loss[k] * (batch_size / new_entries)
				# does train_loss contain all batch_loss from beginning of training????
				for k, v in train_loss.items()
			}
					""")
					# Average the per-batch loss across training.
					# This will give us our average "training loss".
					if train_loss is None:
						train_loss = batch_loss
					else:
						train_loss = {
							k : v * (n_entries / new_entries) + \
								batch_loss[k] * (batch_size / new_entries)
							for k, v in train_loss.items()
						}
					print("train_loss average: {}\n\n".format(train_loss))
					n_entries = new_entries


					if clock and clock['seconds'] < \
							(clock['timer'].get() - clock['mark']):
						logger.critical("\n\nPrint out in progress bar if Timer expired, so stop training, \n\nand set all_done True\n\n")
						tqdm.tqdm.write('Timer expired. Finishing up '
							'training.')
						all_done = True
						break

					logger.critical("\n\nUpdate the progress bar with the current loss.\n\n")
					# Note that `batch_loss` is, in some sense, just the
					# instantaneous training loss. `train_loss` is the average
					# loss across the entire training set so far.
					pbar.set_description('Epoch {}/{}, loss={:.3f}'.format(
						epoch+1, epochs or 'inf', sum(train_loss.values())
					))
					pbar.update(batch_size)

					for k, v in batch_loss.items():
						if math.isnan(v):
							logger.error('Received NaN loss value for '
								'model output "%s". Make sure that your '
								'inputs are all normalized and that the '
								'learning rate is not too high. Sometimes '
								'different algorithms/implementations '
								'work better than others, so you can try '
								'switching optimizers or backend.', k)
							if self.NAN_IS_FATAL:
								raise ValueError('Model loss is NaN.')
						elif math.isinf(v):
							logger.error('Received infinite loss value for '
								'model output "%s". Make sure that your '
								'learning rate is not too high, and that you '
								'clip your gradients.', k)
							if self.NAN_IS_FATAL:
								raise ValueError('Model loss is infinite.')

			logger.critical("\n\nPause timer for train\n\n")
			timers['train'].pause()
			# END: Train one epoch
			###################################################################
			func_stats_save = ("""
# Update our session statistics.
session['epochs'] += 1

# Checkpoint if necessary
run_checkpoint('epochs', allow_validation=False)

# run_posttrain():
# 1. Extract current training loss and
# 2. save current weights to be the best train weights if conditions met
cur_train_loss = run_posttrain(n_entries, train_loss)

# run_validation():
# 1. run validation on a validate provider (model needs compilation again, based on previous training weights)
# 2. update progress bar validation
# 3. save current training weights to best_valid weights folder if condition met
validation_loss = run_validation()

# Execute training hooks.
run_training_hooks(
	cur_train_loss,
	validation_loss,
	status=TrainingHook.EPOCH_END
)

print_times()
			""")


			logger.critical("\n\nAfter each epoch of training, Let's extract outputs, stats, and save weights\n\n%s\n\n", func_stats_save)



			# Update our session statistics.
			session['epochs'] += 1

			# Checkpoint if necessary
			run_checkpoint('epochs', allow_validation=False)

			# Check to see what our current training loss is.
			cur_train_loss = run_posttrain(n_entries, train_loss)

			# Validate
			validation_loss = run_validation()

			# Execute training hooks.
			run_training_hooks(
				cur_train_loss,
				validation_loss,
				status=TrainingHook.EPOCH_END
			)

			#### start here:
			# make plot_weights() working for all image models
			# to make it a hook 
			# let's save weights plots for 1 epoch and every 50 epochs
			def plot_weights():

				# Get the values for the weights from the TensorFlow variable.
				w = idx.load("mnist.best.valid.w/..dense.0+..dense.0_kernel:0.kur")

				# Get the lowest and highest values for the weights.
				# This is used to correct the colour intensity across
				# the images so they can be compared with each other.
				w_min = np.min(w)
				w_max = np.max(w)


				# Create figure with 3x4 sub-plots,
				# where the last 2 sub-plots are unused.
				fig, axes = plt.subplots(3, 4)
				fig.subplots_adjust(hspace=0.3, wspace=0.3)


				for i, ax in enumerate(axes.flat):
					# Only use the weights for the first 10 sub-plots.
					if i<10:
						# Get the weights for the i'th digit and reshape it.
						# Note that w.shape == (img_size_flat, 10)
						image = w[:, i].reshape((28, 28))

						# Set the label for the sub-plot.
						ax.set_xlabel("Weights: {0}".format(i))


						# Plot the image.
						ax.imshow(image, vmin=w_min, vmax=w_max, cmap='seismic')

					if i == 0:
						# how to make a title for plotting
						ax.set_title("validation_loss: {}".format(round(validation_loss[None]['labels'], 3)))

					# Remove ticks from each sub-plot.
					ax.set_xticks([])
					ax.set_yticks([])
				# if we plot while training, we can't save it
				# plt.show()
				plt.savefig('plot_weights/epoch_{}.png'.format(completed_epochs + session['epochs']))


			if completed_epochs + session['epochs'] == 1 or (completed_epochs + session['epochs']) % 100 == 0:
				# save weights plots
				logger.critical("\n\nLet's print weights every 20 epochs\n\n")

				plot_weights()
				# save validation_loss on the plotting

			print_times()

	###########################################################################
	def evaluate(self, provider, callback=None, step=False):
		""" Evaluates the model on some data.

			# Arguments

			provider: Provider instance. The data provider which serves the
				data to be evaluated.
			callback: function or None. If not None, the callback is called
				after each evaluation batch and is passed two parameters:
				`predicted` and `truth`, where `predicted` is the model output
				and `truth` is the ground truth data (if provided by
				`provider`; otherwise, `truth` is set to `None`).

			# Return value

			If `callback` is None, then this returns a tuple `(predicted,
			truth)`, where `predicted` is a dictionary whose keys are the names
			of the output nodes of the model, and whose respective values are
			arrays of predictions (one row per input sample). If the provider
			provides ground truth information, then `truth` has a similar
			structure to `predicted`; if ground truth information is not
			available, then `truth` is None.

			Otherwise, if `callback` is not None, this returns None.
		"""

		self.compile('evaluate', with_provider=provider)

		result = None
		truth = None
		has_truth = None
		total = len(provider)
		n_entries = 0

		#######################################################################
		def store_batch_unknown(batch, evaluated, batch_size):
			""" Saves the batch if we do not know how many entries to expect.
			"""
			nonlocal truth, result

			# We don't know how many entries there will be.
			if result is None:
				# This is our first batch.
				result = {k : [] for k in self.model.outputs}
			for k, v in evaluated.items():
				result[k].extend(v)

			if has_truth:
				if truth is None:
					truth = {k : [] for k in self.model.outputs}
				for k in truth:
					truth[k].extend(batch[k])

		#######################################################################
		def store_batch_known(batch, evaluated, batch_size):
			""" Saves the batch if we know how many entries to expect.
			"""
			nonlocal truth, result

			# We know how many entries there will be.
			if result is None:
				# This is our first batch.
				result = {k : [None]*total for k in evaluated}
			for k, v in evaluated.items():
				result[k][n_entries:(n_entries+batch_size)] = v[:]

			if has_truth:
				if truth is None:
					truth = {k : [None]*total for k in evaluated}
				for k in truth:
					truth[k][n_entries:(n_entries+batch_size)] = batch[k][:]

		store_batch = store_batch_unknown if total is None \
			else store_batch_known

		eval_func = self.retry(
			self.model.backend.evaluate,
			self.auto_retry
		)

		with tqdm.tqdm(
					total=total,
					unit='samples',
					desc='Evaluating'
				) as pbar:

			for num_batches, batch in parallelize(enumerate(provider)):

				if step:
					self.do_step('Evaluate', num_batches, batch)

				try:
					evaluated, _ = eval_func(model=self.model, data=batch)
				except RetryException:
					continue

				if step and logger.isEnabledFor(logging.DEBUG):
					print(evaluated)

				batch_size = len(get_any_value(batch))

				# Check to see if we have truth data available.
				if has_truth is None:
					has_truth = all(k in batch for k in self.model.outputs)

				if callback is None:
					# There is no callback. We need to hang on to everything.
					store_batch(batch, evaluated, batch_size)
				else:
					callback(evaluated, truth)

				n_entries += batch_size
				pbar.update(batch_size)

		if callback is not None:
			return

		for data in (result, truth):
			if data is not None:
				for k, v in data.items():
					data[k] = numpy.array(v)

		if truth is not None:
			for k, v in truth.items():
				result[k] = numpy.reshape(result[k], v.shape)

		return result, truth

	###########################################################################
	def do_step(self, what, num_batches, batch):
		""" Wait for user input before running a single batch of data.
		"""
		print('{}, Batch {}:'.format(what, num_batches+1))
		if logger.isEnabledFor(logging.DEBUG):
			for k, v in batch.items():
				print('{} {}: {}'.format(
					k,
					v.shape if hasattr(v, 'shape') else \
						'(list, {} entries)'.format(len(v)),
					v
				))
		input('Press ENTER to continue...')

	###########################################################################
	def retry(self, func, enabled=True):
		""" Creates a wrapper that implements some retry semantics.
		"""

		def try_func(*args, **kwargs):
			""" Wraps a function with some retry logic.
			"""
			try:
				result = func(*args, **kwargs)

			# Catch Exception so that we don't catch KeyboardInterrupt.
			except Exception:
				if not try_func.enabled:
					raise

				try_func.counter += 1
				if try_func.counter > Executor.MAX_RETRIES:
					logger.exception(
						'Failed to execute on batch. No more retries.')
					raise
				logger.exception('Failed to execute on batch. Tolerating up '
					'to %d more consecutive failures.',
					Executor.MAX_RETRIES - try_func.counter)
				raise RetryException
			else:
				try_func.counter = 0
				return result
		try_func.counter = 0
		try_func.enabled = enabled

		return try_func

### EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF
