# added_features
################################
# create temporal folders
import tempfile

################################
# prepare logger functionality
# import logging
import matplotlib.pyplot as plt
import numpy as np
# logger = logging.getLogger(__name__)
# from .utils import DisableLogging
# with DisableLogging(): how to disable logging for a function
# if logger.isEnabledFor(logging.WARNING): work for pprint(object.__dict__)

################################
# prepare examine tools
from pdb import set_trace
from pprint import pprint
from inspect import getdoc, getmembers, getsourcelines, getmodule, getfullargspec, getargvalues
# to write multiple lines inside pdb
# !import code; code.interact(local=vars())

################################
# use pytorch to do tensor ops, layers, activations
import torch
from torch.autograd import Variable
import torch.nn.functional as F

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

import numpy

from ..utils import idx, package
from . import Supplier
from ..sources import VanillaSource

###############################################################################
class XYSupplier(Supplier):
	""" A supplier which supplies MNIST image/label pairs. These are downloaded
		from the internet, verified, and parsed as IDX files.
	"""

	###########################################################################
	@classmethod
	def get_name(cls):
		""" Returns the name of the supplier.
		"""
		return 'xy'

	###########################################################################
	# x and y are dicts extracted from {xy: {x: {}, y: {}}}
	def __init__(self, x, y, *args, **kwargs):
		""" Creates a new MNIST supplier.

			# Arguments

			labels: str or dict. If str, the path to the IDX file containing
				the image labels. If a dict, it should follow one of these
				formats:

				1. {"url" : URL, "checksum" : SHA256, "path" : PATH}, where URL
				   is the source URL (if the image file needs downloading),
				   SHA256 is the SHA-256 hash of the file (optional, and can be
				   missing or None to skip the verification), and PATH is the
				   path to save the file in (if missing or None it defaults to
				   the system temporary directory).

			images: str or dict. Specifies where the MNIST images can be found.
				Accepts the same values as `labels`.
		"""

		super().__init__(*args, **kwargs)

		self.data = {
						# MnistSupplier._get_filename is staticmethod can be used in __init__
			'x' :
				# VanillaSource.data == numpy.array
				VanillaSource(idx.load(XYSupplier._get_filename(x))
				# dataset.shape = (60000, 28, 28)
			),
			'y' :
				VanillaSource(idx.load(XYSupplier._get_filename(y))
			)
		}

	###########################################################################
	@staticmethod
	def _onehot(source):
		onehot = numpy.zeros((len(source), 10))
		for i, row in enumerate(source.data):
			onehot[i][row] = 1
		source.data = onehot

		return source

	###########################################################################
	@staticmethod
	def _normalize(source):
		# Numpy won't automatically promote the uint8 fields to float32.

		source.data = source.data.astype(numpy.float32)

		# Normalize
		source.data /= 255
		source.data -= source.data.mean()

		source.data = numpy.expand_dims(source.data, axis=-1)

		return source

	###########################################################################
	@staticmethod
	def _get_filename(target):
		""" Returns the filename associated with a particular target.

			# Arguments

			target: str or dict. The target specification. For locally-stored
				files, it can be a string (path to file) or a dictionary with
				key 'local' that contains the file path. For network files,
				it is a dictionary with 'url' (source URL); it may also
				optionally contain 'sha256' (SHA256 checksum) and 'path' (local
				storage directory for the file).

			# Return value

			String to the file's locally stored path. May not exist.
		"""

		if isinstance(target, str):
			target = {'path' : target}
		path, _ = package.install(
			url=target.get('url'),
			path=target.get('path'),
			checksum=target.get('checksum')
		)
		return path

	###########################################################################
	def get_sources(self, sources=None):
		""" Returns all sources from this provider.
		"""

		if sources is None:
			sources = list(self.data.keys())
		elif not isinstance(sources, (list, tuple)):
			sources = [sources]

		for source in sources:
			if source not in self.data:
				raise KeyError(
					'Invalid data key: {}. Valid keys are: {}'.format(
						source, ', '.join(str(k) for k in self.data.keys())
				))

		return {k : self.data[k] for k in sources}

### EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF.EOF
