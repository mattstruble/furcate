# Copyright (c) 2020 Matt Struble. All Rights Reserved.
#
# Use is subject to license terms.
#
# Author: Matt Struble
# Date: Nov. 18 2020
def get_gpus(framework):
    if framework == 'tf':
        import tensorflow as tf
        gpus = tf.config.list_physical_devices('GPU')
    else:
        raise TypeError("The supplied framework '{}' is not supported.".format(framework))

    return gpus

def set_gpus(index, framework):
    gpus = get_gpus(framework)

    if framework == 'tf':
        import tensorflow as tf
        tf.config.set_visible_devices(gpus[int(index)], 'GPU')
    else:
        raise TypeError("The supplied framework '{}' is not supported.".format(framework))