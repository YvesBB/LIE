

"""
Goals: How to use the following
1. K.constant()
2. K.placeholder()
3. Input()
"""

from tensorflow.contrib.keras.python.keras.layers import Input

from prep_data_utils_01_save_load_large_arrays_bcolz_np_pickle_torch import bz_load_array

test_img_array = bz_load_array("/Users/Natsume/Downloads/data_for_all/dogscats/results/test_img_array")

from tensorflow.contrib.keras.python.keras import backend as K


input = K.constant(test_img_array, name='test_img_tensor')
"""
Inputs:
- value: scalar or array is a must
- dtype, shape: optional, can be inferred from value or array
- name are optional, but good to have one

Return:
- tensor

def constant(value, dtype=None, shape=None, name=None):

('Creates a constant tensor.\n'
 '\n'
 'Arguments:\n'
 '    value: A constant value (or list)\n'
 '    dtype: The type of the elements of the resulting tensor.\n'
 '    shape: Optional dimensions of resulting tensor.\n'
 '    name: Optional name for the tensor.\n'
 '\n'
 'Returns:\n'
 '    A Constant Tensor.')
 """

input_placeholder1 = K.placeholder((24,24,4), name='test_img_placeholder')
input_placeholder2 = K.placeholder(test_img_array.shape, name='test_img_placeholder')
ndim_p = K.placeholder(ndim=3, name="ndim")


"""
Inputs:
- shape, ndim, dtype, sparse, name are all optional
- between shape and ndim, at least one is must given
- if both used, shape overwrite ndim
- name: best have

Return:
- a placeholder tensor: empty inside, just empty structured hives
- sess.run(placeholder_tensor, feed_dict={name: value})
- 'Tensor names' must be of the form "<op_name>:<output_index>".

def placeholder(shape=None, ndim=None, dtype=None, sparse=False, name=None):
('Instantiates a placeholder tensor and returns it.\n'
 '\n'
 'Arguments:\n'
 '    shape: Shape of the placeholder\n'
 '        (integer tuple, may include `None` entries).\n'
 '    ndim: Number of axes of the tensor.\n'
 '        At least one of {`shape`, `ndim`} must be specified.\n'
 '        If both are specified, `shape` is used.\n'
 '    dtype: Placeholder type.\n'
 '    sparse: Boolean, whether the placeholder should have a sparse type.\n'
 '    name: Optional name string for the placeholder.\n'
 '\n'
 'Returns:\n'
 '    Tensor instance (with Keras metadata included).\n'
 '\n'
"""
# tensor = K.constant, return a constant tensor
input_tensor = Input(tensor=input)

# tensor = K.placeholder, return a placeholder tensor
input_tensor1 = Input(tensor=input_placeholder1)
# tensor = K.placeholder, return a placeholder tensor
input_tensor2 = Input(tensor=input_placeholder2)

# shape is set, then num_samples is ? or arbitrary
input_tensor3 = Input(shape=input_placeholder1.shape)

# batch_shape is set, then num_samples is specified
input_tensor4 = Input(batch_shape=input_placeholder2.shape)

"""
Inputs:
- shape, batch_shape, tensor, one of them must be given
- tensor:
	- if K.constant, then return a K.constant tensor
	- if K.placeholder, then return a K.placeholder tensor
- dtype: inferred
- name: best to give
- sparse: true or false (true, most values are 0s; false, make it not)

def Input(
  '    shape=None,\n',
  '    batch_shape=None,\n',
  '    name=None,\n',
  '    dtype=K.floatx(),\n',
  '    sparse=False,\n',
  '    tensor=None ):\n',

('`Input()` is used to instantiate a Keras tensor.\n'
 '\n'
 'A Keras tensor is a tensor object from the underlying backend\n'
 '(Theano or TensorFlow), which we augment with certain\n'
 'attributes that allow us to build a Keras model\n'
 'just by knowing the inputs and outputs of the model.\n'
 '\n'
 'For instance, if a, b and c are Keras tensors,\n'
 'it becomes possible to do:\n'
 '`model = Model(input=[a, b], output=c)`\n'
 '\n'
 'The added Keras attribute is:\n'
 '    `_keras_history`: Last layer applied to the tensor.\n'
 '        the entire layer graph is retrievable from that layer,\n'
 '        recursively.\n'
 '\n'
 'Arguments:\n'
 '    shape: A shape tuple (integer), not including the batch size.\n'
 '        For instance, `shape=(32,)` indicates that the expected input\n'
 '        will be batches of 32-dimensional vectors.\n'
 '    batch_shape: A shape tuple (integer), including the batch size.\n'
 '        For instance, `batch_shape=(10, 32)` indicates that\n'
 '        the expected input will be batches of 10 32-dimensional vectors.\n'
 '        `batch_shape=(None, 32)` indicates batches of an arbitrary number\n'
 '        of 32-dimensional vectors.\n'
 '    name: An optional name string for the layer.\n'
 '        Should be unique in a model (do not reuse the same name twice).\n'
 "        It will be autogenerated if it isn't provided.\n"
 '    dtype: The data type expected by the input, as a string\n'
 '        (`float32`, `float64`, `int32`...)\n'
 '    sparse: A boolean specifying whether the placeholder\n'
 '        to be created is sparse.\n'
 '    tensor: Optional existing tensor to wrap into the `Input` layer.\n'
 '        If set, the layer will not create a placeholder tensor.\n'
 '\n'
 'Returns:\n'
 '    A tensor.\n'
"""
