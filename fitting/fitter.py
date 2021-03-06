import os
import nlopt
import emcee
# import warnings
import numpy as np
from scipy.optimize import fmin
from scipy.optimize import fmin_slsqp
try:
    from scipy.optimize import differential_evolution
except ImportError as ex:
    print(ex)
    differential_evolution = None

from pyterpol3.synthetic.auxiliary import parlist_to_list
from pyterpol3.synthetic.auxiliary import string2bool
from pyterpol3.synthetic.auxiliary import read_text_file
from pyterpol3.synthetic.auxiliary import renew_file

fitters = dict(
    sp_nelder_mead=dict(par0type='value',
                        optional_kwargs=['xtol', 'ftol', 'maxiter', 'maxfun'],
                        object=fmin,
                        uses_bounds=False,
                        info='Nelder-Mead simplex algorithm. '
                             'Implemetation: http://docs.scipy.org/doc/scipy-0.16.1/reference/generated/'
                             'scipy.optimize.fmin.html#scipy.optimize.fmin Ineffective for high dimensional'
                             ' parameter space.'),
    sp_slsqp=dict(par0type='value',
                  optional_kwargs=['ftol'],
                  object=fmin_slsqp,
                  uses_bounds=True,
                  info='Sequential Least Square Programming. '
                       'Implemetation: http://docs.scipy.org/doc/scipy-0.16.1/reference/generated/'
                       'scipy.optimize.fmin.html#scipy.optimize.fmin Ineffective for high dimensional'
                       ' parameter spacse.'),
    sp_diff_evol=dict(par0type='limit',
                      optional_kwargs=['popsize', 'tol', 'strategy', 'maxiter'],
                      object=differential_evolution,
                      uses_bounds=False,
                      info='Differential evolution algorithm.'
                           'Implemetation: http://docs.scipy.org/doc/scipy-0.16.1/reference/generated/'
                           'scipy.optimize.fmin.html#scipy.optimize.fmin.'),
    nlopt_nelder_mead=dict(par0type='value',
                           optional_kwargs=['xtol', 'ftol', 'maxfun'],
                           object=None,
                           environment=nlopt.LN_NELDERMEAD,
                           uses_bounds=True,
                           info='Nelder-Mead Simplex. Implementation NLOPT: Steven G. Johnson, '
                                'The NLopt nonlinear-optimization package, http://ab-initio.mit.edu/nlopt.'),
    nlopt_sbplx=dict(par0type='value',
                     optional_kwargs=['xtol', 'ftol', 'maxfun'],
                     object=None,
                     environment=nlopt.LN_SBPLX,
                     uses_bounds=True,
                     info='Sbplx - a variation of the Tom Rowans Subplex. '
                          'Implementation NLOPT: Steven G. Johnson, The NLopt '
                          'nonlinear-optimization package, http://ab-initio.mit.edu/nlopt.'),
)


class Fitter(object):
    """
    """
    def __init__(self, name=None, fitparams=None, verbose=False, debug=False, fitlog='fit.log', **kwargs):
        """
        :param name: name of the fitting environment
        :param fitparams a list of Parameter types
        :param verbose whether to save detailed chi_square information
        :param debug: debugmode
        :param fitlog: file in which the fitting is logged
        :param kwargs: fitting environment control keywords
        :return:
        """

        # pass the parameters
        if fitparams is None:
            self.fitparams = []
        else:
            self.fitparams = fitparams
        self.verbose = verbose
        self.fitlog = fitlog
        self.debug = debug
        self.fittername = name

        # empty parameters
        self.fitter = None
        self.fit_kwargs = {}
        self.par0 = []
        self.uses_bounds = False
        self.family = None
        self.vmins = None
        self.vmaxs = None
        self.nlopt_environment = None

        # empty list of all trial fits
        self.iters = []
        self.parameter_identification = None

        # iteration number
        self.iter_number = 0

        # choose a fitter if one
        # was given
        if name is not None:
            self.choose_fitter(name, **kwargs)

    def __call__(self, func, *args):
        """
        :param func:
        :param args:
        :return:
        """
        # emtpy the fitlog
        renew_file(self.fitlog)

        # reset the counter and clear the fitting
        self.iter_number = 0
        self.iters = []

        # debug
        if self.debug:
            print("Started fitted with fitting environment: %s\n" \
                  " vector of parameters: %s and optional" \
                  " enviromental parameters: %s." % (self.fittername, str(self.par0), str(self.fit_kwargs)))

        if len(self.par0) == 0:
            raise ValueError('No initial vector of parameters (wrapped in Parameter class) was passed.')

        # check that initial parameters do not lie outside the fitted region.
        self.check_initial_parameters()

        # run fitting
        if self.family == 'sp':
            if self.uses_bounds:
                bounds = [[vmin, vmax] for vmin, vmax in zip(self.vmins, self.vmaxs)]
                self.result = self.fitter(func, self.par0, args=args, bounds=bounds, **self.fit_kwargs)
            else:
                self.result = self.fitter(func, self.par0, args=args, **self.fit_kwargs)

        elif self.family == 'nlopt':

            # define function for the nlopt fitter
            def f(x, grad):
                return func(x, *args)

            # check that we are searching minimum
            self.fitter.set_min_objective(f)

            # the fitting
            self.result = self.fitter.optimize(self.par0)

        # we want only set of parameters for the result
        # very in elegant
        if not isinstance(self.result, (list, tuple, type(np.array([])))):
            self.result = self.result.x

    def __str__(self):
        """
        String representation of the class.
        :return:
        """
        string = ''
        string += 'Fitter: %s optional_arguments: %s\n' % (self.fittername, str(self.fit_kwargs))
        string += 'Initial parameters:'
        for i, par in enumerate(self.fitparams):
            string += "(%s, g.): (%s, %s); " % (par['name'], str(self.par0[i]), str(par['group']))
            if (i + 1) % 5 == 0:
                string += '\n'
        string += '\n'

        return string

    def append_iteration(self, iter):
        """
        Appends each iteration.
        :param iter the iteration
        :return:
        """
        # TODO this function  has to be improved.
        self.iter_number += 1
        # print iter
        self.iters.append(iter)

        # if the number of iterations exceeds a certain number
        # they are written to a file
        if self.iter_number % 1000 < 1:
            self.flush_iters()
            self.iters = []

    def clear_all(self):
        """
        :return:
        """
        self.__init__()

    def check_initial_parameters(self):
        """
        Checks that initial parameters do not lie outside the fitted region.
        :return:
        """
        p0 = self.par0
        for i, p in enumerate(self.fitparams):
            
            # differential evolution uses interval as a p0, and
            # this function tests only floats
            if isinstance(p0[i], (list, tuple)):
                continue
            if (p0[i] > p['vmax']) | (p0[i] < p['vmin']):
                raise ValueError('Parameter %s (group %i) lies outside the fitted regions! %f not in (%f, %f)' %
                                 (p['name'], p['group'], p['value'], p['vmin'], p['vmax']))

    def choose_fitter(self, name, fitparams=None, init_step=None, **kwargs):
        """
        Selects a fitter from the list of available ones and
        prepares the fitting variables.
        :param name: name of the fitting environment
        :param fitparams: list of fitted parameters ech wrapped within Parameter class
        :param kwargs: keyword arguments controlling the respective fitting environement
        :return:
        """
        # clear the class first
        self.clear_all()

        # check the input
        if name.lower() not in list(fitters.keys()):
            raise ValueError('Fitter: %s is unknown. Registered fitters are:\n %s.' % (name, self.list_fitters()))
        else:
            self.fitter = fitters[name]['object']
            self.fittername = name
        for key in list(kwargs.keys()):
            if key not in fitters[name]['optional_kwargs']:
                raise KeyError('The parameter: %s is not listed among '
                               'optional_kwargs for fitter: %s. The eligible'
                               'optional_kwargs are: %s' % (key, name, str(fitters[name]['optional_kwargs'])))
            else:
                self.fit_kwargs[key] = kwargs[key]

        if self.debug:
            print('Choosing environment: %s\n' \
                  ' environmental parameters: %s.' % (name, str(self.fit_kwargs)))

        # if we want to change the fitted parameters
        if fitparams is None:
            fitparams = self.fitparams
        else:
            self.fitparams = fitparams

        # set up initial value
        if fitters[name]['par0type'] == 'value':
            self.par0 = parlist_to_list(fitparams, property='value')
        if fitters[name]['par0type'] == 'limit':
            vmins = parlist_to_list(fitparams, property='vmin')
            vmaxs = parlist_to_list(fitparams, property='vmax')
            self.par0 = [[vmin, vmax] for vmin, vmax in zip(vmins, vmaxs)]

        if self.debug:
            print('Setting initial parameters: %s' % str(self.par0))

        # checks that there are any fitting boundaries
        if fitters[name]['uses_bounds']:
            self.uses_bounds = True
            self.vmins = parlist_to_list(fitparams, property='vmin')
            self.vmaxs = parlist_to_list(fitparams, property='vmax')
        else:
            self.uses_bounds = False

        # set up family
        self.family = name.split('_')[0]

        if self.family == 'nlopt':
            self.nlopt_environment = fitters[name]['environment']
            self.setup_nlopt(init_step=init_step)

    def flush_iters(self, f=None):
        """
        Flushes all records within self.iters to a file
        :param f: filename
        :return:
        """
        if f is None:
            f = self.fitlog

        # create a block of lines
        lines = []

        # if the file is empty add header
        # print os.path.getsize(self.fitlog)
        if os.path.getsize(self.fitlog) == 0:
            # construct the header
            header = self.make_header()
            lines.append(header)

        for row in self.iters:
            line = ''

            # create a row of parameters + chi2
            p = row['parameters']
            d = np.zeros(len(p)+1)
            d[:-1] = p
            d[-1] = row['chi2']

            for i in range(0, len(d)):
                line += '%s ' % str(d[i])
            line += '\n'
            # append the row
            lines.append(line)
            # print line

        # write the to a file
        ofile = open(f, 'a')
        ofile.writelines(lines)
        ofile.close()

    def run_mcmc(self, chi_square, chain_file, fitparams, nwalkers, niter, *args):
        """
        :param chi_square
        :param fitparams
        :param nwalkers
        :param niter
        :param args
        :return:
        """

        def lnlike(pars, *args):
            """
            Model probability.
            :param pars:
            :param args:
            :return:
            """
            return -0.5*chi_square(pars, *args)

        # define the boundaries and the priors
        def lnprior(pars):
            """
            Prior probabilities i.e. boundaries.
            :param pars:
            :return:
            """

            for p, vmin, vmax in zip(pars, self.vmins, self.vmaxs):
                if (p < vmin) | (p > vmax):
                    return -np.inf
            return 0.0

        def lnprob(pars, *args):
            """
            The full probability function.
            :param pars:
            :param args:
            :return:
            """
            lp = lnprior(pars)
            if not np.isfinite(lp):
                return -np.inf
            return lp + lnlike(pars, *args)

        # get the dimensions
        ndim = len(fitparams)

        # initialize the sampler
        pos = np.array([[wmin + (wmax - wmin) * np.random.rand() for wmin, wmax in zip(self.vmins, self.vmaxs)]
                        for i in range(nwalkers)])

        # setup the sampler
        sampler = emcee.EnsembleSampler(nwalkers, ndim, lnprob, args=args)

        # initialize the file - create the header
        if self.parameter_identification is not None:
            header = [self.make_header()]
        else:
            header = ['']

        # write the header and close the file
        ofile = open(chain_file, 'w')
        ofile.writelines(header)
        ofile.close()

        # run the sampler
        for state in sampler.sample(pos, iterations=niter, store=False):
            coords = state.coords
            ofile = open(chain_file, 'a')
            for k in range(coords.shape[0]):
                ofile.write("%d %s %f\n" % (k, " ".join(['%.12f' % i for i in coords[k]]), state.log_prob[k]))
            ofile.close()

    @staticmethod
    def list_fitters():
        """
        Lists all fitters.
        :return: string : a list of all fitters.
        """
        string = '\n'.rjust(100, '=')
        for key in list(fitters.keys()):
            string += "Name: %s\n" % key
            string += "Optional parameters: %s\n" % str(fitters[key]['optional_kwargs'])
            string += "Uses boundaries: %s\n" % str(fitters[key]['uses_bounds'])
            string += "Description: %s\n" % fitters[key]['info']
            string += '\n'.rjust(100, '=')
        return string

    def load(self, f):
        """
        Loads the text representation of the class from
        a file f.
        :param f
        :return:
        """

        # read the file
        lines = read_text_file(f)
        data_start = len(lines)
        for i, l in enumerate(lines):
            if l.find('FITTER') > -1:
                data_start = i
                break

        # check that there are actually some data in the file
        if data_start >= len(lines):
            return False

        # create the class
        fitter = Fitter()

        name = None
        fit_kwargs = {}
        # from here the file is actually being read
        for i, l in enumerate(lines[data_start+1:]):

            # once we reach FITTER again we end
            if l.find('FITTER') > -1:
                break
            # split the line
            d = l.split()
            # print d
            # save the name
            if d[0].find('fitter:') > -1:
                name = d[1]

            # save the kwargs
            elif d[0].find('fit_parameters:') > -1:
                d = d[1:]
                if len(d) < 2:
                    continue
                fit_kwargs = {d[i].strip(':'): float(d[i+1]) for i in range(0, len(d), 2)}

            # do the same for enviromental keys
            if d[0].find('env_keys:') > -1:
                # the first string is just identification
                d = d[1:]

                # secure corrct types
                recs = ['debug', 'verbose', 'fitlog']
                cast_types = [string2bool, string2bool, str]
                cdict = {d[i].rstrip(':'): d[i+1] for i in range(0, len(d), 2)}
                for k in list(cdict.keys()):
                    if k in recs:
                        i = recs.index(k)
                        ctype = cast_types[i]
                        cdict[k] = ctype(cdict[k])

                    # assign the vlues
                    setattr(fitter, k, cdict[k])

        # choose the fitter
        if name != 'None':
            fitter.choose_fitter(name, **fit_kwargs)
        else:
            return False

        # finally assign everything to self
        attrs = ['debug', 'fittername', 'verbose', 'fitlog', 'fit_kwargs']
        for attr in attrs:
            setattr(self, attr, getattr(fitter, attr))

        # if we got here, we loaded the data
        return True

    def make_header(self):
        """
        Creates the header for output file.
        :return:
        """
        header = ''
        for key in list(self.parameter_identification.keys()):
            if key != 'value':
                header += '# %s: ' % key
                for rec in self.parameter_identification[key]:
                    header += '%s ' % str(rec)
            header += '\n'

        return header

    def save(self, ofile):
        """
        Saves the class. It should be retrievable from the file.
        Since this class really cannot exist without the
        interface, it really saves only the selected fitting
        environment and fitted kwargs.
        :param ofile:
        :return:
        """
        # Open the file
        if isinstance(ofile, str):
            ofile = open(ofile, 'w+')

        # row announcing the fitter
        string = ' FITTER '.rjust(105, '#').ljust(200, '#') + '\n'
        # name of the fitter
        string += 'fitter: %s\n' % self.fittername
        string += 'fit_parameters: '
        # writes the fitting kwargs
        for fkey in self.fit_kwargs:
            string += '%s: %s ' % (fkey, str(self.fit_kwargs[fkey]))
        string += '\n'

        # writes enfiromental keys
        enviromental_keys = ['debug', 'verbose', 'fitlog']
        string += 'env_keys: '
        for fkey in enviromental_keys:
            string += "%s: %s " % (fkey, str(getattr(self, fkey)))
        string += '\n'
        string += ' FITTER '.rjust(105,    '#').ljust(200, '#') + '\n'
        # write the remaining parameters
        ofile.writelines(string)

    def setup_nlopt(self, init_step=None):
        """
        Sets up the the NLOPT fitter.
        :return:
        """

        if self.debug:
            print("Setting up NLOPT minimizer.")

        # length of the fitted parameters
        n = len(self.fitparams)

        # configures the fitter
        self.fitter = nlopt.opt(self.nlopt_environment, n)

        # setup parameters for fitting terminatio
        for key in list(self.fit_kwargs.keys()):
            if key == 'xtol':
                self.fitter.set_xtol_rel(self.fit_kwargs[key])
            if key == 'ftol':
                self.fitter.set_ftol_rel(self.fit_kwargs[key])
            if key == 'maxfun':
                self.fitter.set_maxeval(self.fit_kwargs[key])

        # setup boundaries
        if self.uses_bounds:
            self.fitter.set_lower_bounds(self.vmins)
            self.fitter.set_upper_bounds(self.vmaxs)

        # setup initial step, which can be either
        # user-defined or default
        if init_step is None:
            stepsize = (np.array(self.vmaxs) - np.array(self.vmins)) / 4.
            stepsize = stepsize.tolist()
        else:
            stepsize = init_step

        self.fitter.set_initial_step(stepsize)

    def set_lower_boundary(self, arr):
        """
        Sets lower boundary.
        :param arr:
        :return:
        """

        self.vmins = arr

    def set_upper_boundary(self, arr):
        """
        Sets upper boundary.
        :param arr:
        :return:
        """

        self.vmaxs = arr

    def set_fit_properties(self, pi):
        """
        Sets identification of parameters i.e. names, groups and components
        :param pi: dictionary with the records for each parameter
                the order have to be the same as for the fitted parameter
        :return:
        """
        self.parameter_identification = pi



















