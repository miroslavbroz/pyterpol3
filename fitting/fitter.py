import os
import nlopt
import warnings
import numpy as np
from scipy.optimize import fmin
from scipy.optimize import differential_evolution
from pyterpol.synthetic.auxiliary import parlist_to_list

fitters = dict(
    sp_nelder_mead=dict(par0type='value',
                        optional_kwargs=['xtol', 'ftol', 'maxiter', 'maxfun'],
                        object=fmin,
                        uses_bounds=False,
                        info='Nelder-Mead simplex algorithm. '
                             'Implemetation: http://docs.scipy.org/doc/scipy-0.16.1/reference/generated/' \
                             'scipy.optimize.fmin.html#scipy.optimize.fmin Ineffective for high dimensional' \
                             ' parameter space.'
                        ),
    sp_diff_evol=dict(par0type='limit',
                        optional_kwargs=['popsize', 'tol', 'strategy', 'maxiter'],
                        object=differential_evolution,
                        uses_bounds=False,
                        info='Differential evolution algorithm.'
                             'Implemetation: http://docs.scipy.org/doc/scipy-0.16.1/reference/generated/' \
                             'scipy.optimize.fmin.html#scipy.optimize.fmin.'
                        ),
    nlopt_nelder_mead=dict(par0type='value',
                           optional_kwargs=['xtol', 'ftol', 'maxfun'],
                           object = None,
                           environment = nlopt.LN_NELDERMEAD,
                           uses_bounds=True,
                           info='Nelder-Mead Simplex. Implementation NLOPT: Steven G. Johnson, '
                                'The NLopt nonlinear-optimization package, http://ab-initio.mit.edu/nlopt.'
                           ),
    nlopt_sbplx=dict(par0type='value',
                           optional_kwargs=['xtol', 'ftol', 'maxfun'],
                           object = None,
                           environment = nlopt.LN_SBPLX,
                           uses_bounds=True,
                           info='Sbplx - a variation of the Tom Rowans Subplex. '
                                'Implementation NLOPT: Steven G. Johnson, The NLopt '
                                'nonlinear-optimization package, http://ab-initio.mit.edu/nlopt.'
                           ),
)

class Fitter(object):
    """
    """
    def __init__(self, fitparams=[], verbose=False, debug=False, fitlog='fit.log'):
        """
        :param fitparams a list of Parameter types
        :param verbose whether to save detailed chi_square information
        :param debug
        :return:
        """

        # pass the parameters
        self.fitparams = fitparams
        self.verbose = verbose
        self.fitlog = fitlog
        self.debug = debug

        # empty parameters
        self.fitter = None
        self.fittername = None
        self.fit_kwargs = {}
        self.par0 = []
        self.uses_bounds = False
        self.family = None
        self.vmins = None
        self.vmaxs = None
        self.nlopt_environment = None

        # empty list of all trial fits
        self.iters = []

        # clear the fitting log
        if os.path.isfile(fitlog):
            warnings.warn('A fitlog from previous fitting was found and overwritten..muhahahaha!')
            open(fitlog, 'w')


    def __call__(self, func, *args, **kwargs):
        """
        :param func:
        :param args:
        :param kwargs:
        :return:
        """
        # reset the counter and clear the fitting
        self.iter_number = 0
        self.iters = []

        # debug
        if self.debug:
            print "Started fitted with fitting environment: %s\n" \
                  " vector of parameters: %s and optional" \
                  " enviromental parameters: %s." % (self.fittername, str(self.par0), str(self.fit_kwargs))

        if len(self.par0) == 0:
            raise ValueError('No initial vector of parameters (wrapped in Parameter class) was passeed.')

        # run fitting
        if self.family == 'sp':
            if self.uses_bounds:
                bounds = [[vmin, vmax] for vmin, vmax in zip(self.vmins, self.vmaxs)]
                self.result = self.fitter(func, self.par0, args=args, bounds=bounds, **self.fit_kwargs)
            else:
                self.result = self.fitter(func, self.par0, args=args, **self.fit_kwargs)

        elif self.family == 'nlopt':

            f = lambda x, grad: func(x, *args)

            # print self.par0

            # check that we are searching minimum
            self.fitter.set_min_objective(f)

            # the fitting
            self.result = self.fitter.optimize(self.par0)

    def __str__(self):
        """
        String representation of the class.
        :return:
        """
        string = 'Initial parameters:'
        string += 'Fitter: %s optional_arguments: %s\n' % (self.fittername, str(self.fit_kwargs))
        for i, par in enumerate(self.fitparams):
            string += "(%s, group): (%s, %s); " % (par['name'], str(self.par0[i]), str(par['group']))
        string += '\n'

        return string

    def append_iteration(self, iter):
        """
        Appends each iteration.
        :return:
        """
        self.iter_number += 1
        self.iters.append(iter)

        # if the number of iterations exceeds a certain number
        # they are written to a file
        if len(self.iters) > 1000:
            self.flush_iters()
            self.iters = []

    def choose_fitter(self, name, fitparams=None, **kwargs):
        """
        Prepares the variables for the fitting
        :param name:
        :param kwargs:
        :return:
        """
        # print fitparams

        # check the input
        if name.lower() not in fitters.keys():
            raise ValueError('Fitter: %s is unknown. Registered fitters are:\n %s.' % (name, self.list_fitters()))
        else:
            self.fitter = fitters[name]['object']
            self.fittername = name
        for key in kwargs.keys():
            if key not in fitters[name]['optional_kwargs']:
                raise KeyError('The parameter: %s is not listed among '
                               'optional_kwargs for fitter: %s. The eligible'
                               'optional_kwargs are: %s'  % (key, name, str(fitters[name]['optional_kwargs'])))
            else:
                self.fit_kwargs[key] = kwargs[key]

        if self.debug:
            print 'Choosing environment: %s\n' \
                  ' environmental parameters: %s.' % (name, str(self.fit_kwargs))

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
            print 'Setting initial parameters: %s' % str(self.par0)

        # checks that there are any fitting boundaries
        if fitters[name]['uses_bounds']:
            self.uses_bounds = True
            self.vmins = parlist_to_list(fitparams, property='vmin')
            self.vmaxs = parlist_to_list(fitparams, property='vmax')

        # set up family
        self.family = name.split('_')[0]

        if self.family == 'nlopt':
            self.nlopt_environment = fitters[name]['environment']
            self.setup_nlopt()

    def flush_iters(self, f=None):
        """
        Flushes all records within self.iters to a file
        :param f:
        :return:
        """
        if f is None:
            f = self.fitlog

        # create a block of lines
        lines = []
        for row in self.iters:
            line = ''
            for key in row.keys():
                line += "%s: %s " % (key, str(row[key]))
            line += '\n'
            lines.append(line)

        # write the to a file
        ofile = open(f, 'a')
        ofile.writelines(lines)
        ofile.close()

    def list_fitters(self):
        """
        Lists all fitters.
        :return: string : a list of all fitters.
        """
        string = '\n'.rjust(100, '=')
        for key in fitters.keys():
            string += "Name: %s\n" % key
            string += "Optional parameters: %s\n" % str(fitters[key]['optional_kwargs'])
            string += "Uses boundaries: %s\n" % str(fitters[key]['uses_bounds'])
            string += "Description: %s\n" % fitters[key]['info']
            string += '\n'.rjust(100, '=')
        return string

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
        string += 'fitter: %s\n' % (self.fittername)
        string += 'fit_kwargs:'
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

    def setup_nlopt(self):
        """
        Sets up the the NLOPT fitter.
        :return:
        """

        if self.debug:
            print "Setting up NLOPT minimizer."

        # length of the fitted parameters
        n = len(self.fitparams)

        # configures the fitter
        self.fitter = nlopt.opt(self.nlopt_environment, n)

        # setup parameters for fitting terminatio
        for key in self.fit_kwargs.keys():
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

        # setup initial step
        # TODO Maybe this deserves its attribute variable in Parameter class
        stepsize = ((np.array(self.vmaxs) - np.array(self.vmins))/2.).tolist()
        # print stepsize
        # print self.fitter.get_lower_bounds(), self.fitter.get_upper_bounds()

        self.fitter.set_initial_step(stepsize)



















