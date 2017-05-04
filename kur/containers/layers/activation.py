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

from . import Layer, ParsingError

import logging
import matplotlib.pyplot as plt
import numpy as np
logger = logging.getLogger(__name__)
from ...utils import DisableLogging
# with DisableLogging(): how to disable logging for a function
# if logger.isEnabledFor(logging.WARNING): work for pprint(object.__dict__)
# prepare examine tools
from pdb import set_trace
from pprint import pprint
from inspect import getdoc, getmembers, getsourcelines, getmodule, getfullargspec, getargvalues
# to write multiple lines inside pdb
# !import code; code.interact(local=vars())

###############################################################################
class Activation(Layer):				# pylint: disable=too-few-public-methods
	""" An activation layer.

		Some layers may include an 'activation' keyword. Those layers are
		intended to be equivalent to no-activation followed by this explicit
		activation layer.
	"""

	###########################################################################
	def __init__(self, *args, **kwargs):
		""" Creates a new activation layer.
		"""
		super().__init__(*args, **kwargs)
		self.type = None

	###########################################################################
	def _parse(self, engine):
		""" Parse the layer.
		"""

		# if alpha not exist or empty as None, default value is 0.3
		self.type = self.args['name']
		if self.type == 'leakyrelu':

			if 'alpha' in self.args and self.args['alpha'] is not None:
				self.alpha = self.args['alpha']
			else:
				self.alpha = 0.3


	###########################################################################
	def _build(self, model):
		""" Create the backend-specific placeholder.
		"""
		backend = model.get_backend()
		if backend.get_name() == 'keras':

			import keras.layers as L			# pylint: disable=import-error

			if self.type != "leakyrelu":
				yield L.Activation(
					'linear' if self.type == 'none' or self.type is None \
						else self.type,
					name=self.name,
					trainable=not self.frozen
				)
			# if advanced activation in keras, like LeakyReLU
			else:
				yield L.LeakyReLU(alpha=self.alpha)

		elif backend.get_name() == 'pytorch':

			import torch.nn.functional as F		# pylint: disable=import-error
			func = {
				'relu' : F.relu,
				'tanh' : F.tanh,
				'sigmoid' : F.sigmoid,
				'softmax' : F.log_softmax
			}.get(self.type.lower())
			if func is None:
				raise ValueError('Unsupported activation function "{}" for '
					'backend "{}".'.format(self.type, backend.get_name()))

			def connect(inputs):
				""" Connects the layer.
				"""
				assert len(inputs) == 1
				return {
					'shape' : self.shape([inputs[0]['shape']]),
					'layer' : model.data.add_operation(func)(
						inputs[0]['layer']
					)
				}

			yield connect

		else:
			raise ValueError(
				'Unknown or unsupported backend: {}'.format(backend))

	###########################################################################
	def shape(self, input_shapes):
		""" Returns the output shape of this layer for a given input shape.
		"""
		if len(input_shapes) > 1:
			raise ValueError('Activations only take a single input.')
		input_shape = input_shapes[0]
		return input_shape

### EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF
