from collections import Sequence
import abc
import numbers

import numpy as np

from scipy.stats.distributions import randint
from scipy.stats.distributions import rv_discrete
from scipy.stats.distributions import rv_frozen
from scipy.stats.distributions import uniform

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
from sklearn.utils import check_random_state
from sklearn.utils.fixes import sp_version


class Identity(TransformerMixin):
    """Identity transform."""
    def fit(self, values):
        return self

    def transform(self, values):
        return values

    def inverse_transform(self, values):
        return values


class Log10(TransformerMixin):
    """Base 10 logarithm transform."""
    def fit(self, values):
        return self

    def transform(self, values):
        return np.log10(values)

    def inverse_transform(self, values):
        return 10**np.asarray(values)


class Log(TransformerMixin):
    """Natural logarithm transform."""
    def fit(self, values):
        return self

    def transform(self, values):
        return np.log(values)

    def inverse_transform(self, values):
        return np.exp(values)


class Distribution:
    def transform(self, values):
        """Transform `values` from original into warped space."""
        return self.transformer.transform(values)

    def inverse_transform(self, values):
        """Transform `values` from warped into original space."""
        return self.transformer.inverse_transform(values)

    @abc.abstractmethod
    def rvs(self, n_samples=None, random_state=None):
        """
        Randomly sample points from the original space
        """
        return


class CategoricalEncoder(TransformerMixin):
    """
    OneHotEncoder of scikit-learn that can handle categorical
    variables.
    """
    def __init__(self):
        """Convert labeled categories into one-hot encoded features"""
        self._label = LabelEncoder()
        self._onehot = OneHotEncoder()

    def fit(self, values):
        """
        Fit a list or array of categories.

        Parameters
        ----------
        * `values` [array-like]:
            List of categories.
        """
        vals = np.asarray(values)
        vals = self._label.fit_transform(vals)
        self._onehot.fit(vals.reshape(-1, 1))
        return self

    def transform(self, values):
        """
        Transform an array of categories to a one-hot encoded representation.

        Parameters
        ----------
        * `values` [array-like]:
            List of categories.
        """
        vals = np.asarray(values)
        vals = self._label.transform(vals).reshape(-1, 1)
        return self._onehot.transform(vals).toarray()


class Real(Distribution):
    def __init__(self, low, high, prior='uniform', transformer='identity'):
        """Search space dimension that can take on any real value.

        Parameters
        ----------
        * `low` [float]:
            Lower bound of the parameter. (Inclusive)

        * `high` [float]:
            Upper bound of the parameter. (Exclusive)

        * `prior` [string or rv_frozen, default='uniform']:
            Distribution to use when sampling random points for this parameter.

        * `transformer` [string or fitted TransformerMixin, default='identity']:
            Transformer to convert between original and warped search space.
            Parameter values are always transformed before being handed to the
            optimizer.
        """
        self._low = low
        self._high = high

        if transformer == 'identity':
            self.transformer = Identity()
        elif transformer == "log":
            self.transformer = Log()
        elif transformer == "log10":
            self.transformer = Log10()
        elif isinstance(transformer, TransformerMixin):
            self.transformer = transformer
        else:
            raise RuntimeError('%s is not a valid transformer.'%transformer)

        if prior == 'uniform':
            self._rvs = uniform(self._low, self._high - self._low)
        elif isinstance(prior, rv_frozen):
            self._rvs = prior
        else:
            raise ValueError(
                "prior should be either 'uniform' or a rv frozen object. "
                "Got %s" % self._rvs)

    def rvs(self, n_samples=None, random_state=None):
        random_vals = self._rvs.rvs(size=n_samples, random_state=random_state)
        return np.clip(random_vals, low, high)


class Integer(Distribution):
    def __init__(self, low, high, prior='uniform', transformer='identity'):
        """Search space dimension that can take on integer values.

        Parameters
        ----------
        * `low` [float]
            Lower bound of the parameter.

        * `high` [float]
            Upper bound of the parameter.

        * `prior` [string or rv_frozen, default='uniform']:
            Distribution to use when sampling random points for this parameter.

        * `transformer` [string or fitted TransformerMixin, default='identity']:
            Transformer to convert between original and warped search space.
            Parameter values are always transformed before being handed to the
            optimizer.
        """
        self._low = low
        self._high = high

        if transformer == 'identity':
            self.transformer = Identity()
        elif isinstance(transformer, TransformerMixin):
            self.transformer = transformer
        else:
            raise RuntimeError('%s is not a valid transformer.'%transformer)

        if prior == 'uniform':
            self._rvs = randint(self._low, self._high)
        elif isinstance(prior, rv_frozen):
            self._rvs = prior
        else:
            raise ValueError(
                "prior should be either 'uniform' or a rv frozen object. "
                "Got %s" % self._rvs)

    def rvs(self, n_samples=None, random_state=None):
        random_vals = self._rvs.rvs(size=n_samples, random_state=random_state)
        return np.clip(random_vals, low, high)


class Categorical(Distribution):
    def __init__(self, *categories, prior=None, transformer='one-hot'):
        """Search space dimension that can take on categorical values.

        Parameters
        ----------
        *categories :
            sequence of possible categories

        * `prior` [array-like, shape=(categories,), default None]:
            Prior probabilities for each category. By default all categories
            are equally likely.

        * `transformer` [string or fitted TransformerMixin, default 'onehot']:
            Transformer to convert between original and warped search space.
            Parameter values are always transformed before being handed to the
            optimizer. Defaults to `CategoryTransform`
            (OneHotEncoder of sklearn that can handle categorical variables).
        """
        self.categories = np.asarray(categories)

        if transformer == 'onehot':
            self.transformer = CategoryTransform()
            self.transformer.fit(self.categories)
        elif transformer == 'labels':
            self.transformer = LabelEncoder()
            self.transformer.fit(self.categories)
        elif isinstance(transformer, TransformerMixin):
            self.transformer = transformer
        else:
            raise RuntimeError('%s is not a valid transformer.'%transformer)

        if prior is None:
            prior = np.tile(1. / len(self.categories), len(self.categories))
        self._rvs = rv_discrete(values=(range(len(self.categories)), prior))

    def rvs(self, n_samples=None, random_state=None):
        choices = self._rvs.rvs(size=n_samples, random_state=random_state)
        return self.categories[choices]


def check_grid(grid):
    # XXX how to detect [(1,2), (3., 5.)] and convert it to
    # XXX [[(1,2), (3., 5.)]] to support sub-grids
    if (isinstance(grid[0], Distribution) or
        (isinstance(grid[0], Sequence)
         and isinstance(grid[0][0], (numbers.Number, str)))):
        grid = [grid]

    # create a copy of the grid that we can modify without
    # interfering with the caller's copy
    grid_ = []
    for sub_grid in grid:
        sub_grid_ = list(sub_grid)
        grid_.append(sub_grid_)

        for i, dist in enumerate(sub_grid_):
            if isinstance(dist, Distribution):
                pass

            elif len(dist) > 2 or isinstance(dist[0], str):
                sub_grid_[i] = Categorical(*dist)

            # important to check for Integral first as int(3) is
            # also a Real but not the other way around
            elif isinstance(dist[0], numbers.Integral):
                sub_grid_[i] = Integer(*dist)
            elif isinstance(dist[0], numbers.Real):
                sub_grid_[i] = Real(*dist)

    return grid_


def sample_points(grid, n_points=1, random_state=None):
    grid_ = check_grid(grid)

    rng = check_random_state(random_state)

    for n in range(n_points):
        sub_grid = grid_[rng.randint(0, len(grid_))]

        params = []
        for dist in sub_grid:
            if sp_version < (0, 16):
                params.append(dist.rvs())
            else:
                params.append(dist.rvs(random_state=rng))
        yield tuple(params)
