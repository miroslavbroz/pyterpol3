# edited by Susanne 21.03.2018
# edited and added lines are marked with # S

# -*- coding: utf-8 -*-
import copy
import corner
# import sys
import warnings
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats

from pyterpol3.synthetic.makespectrum import SyntheticGrid
from pyterpol3.observed.observations import ObservedSpectrum
from pyterpol3.fitting.parameter import Parameter
from pyterpol3.fitting.parameter import parameter_definitions
from pyterpol3.fitting.fitter import Fitter
from pyterpol3.synthetic.auxiliary import generate_least_number
from pyterpol3.synthetic.auxiliary import keys_to_lowercase
from pyterpol3.synthetic.auxiliary import read_text_file
from pyterpol3.synthetic.auxiliary import string2bool
from pyterpol3.synthetic.auxiliary import sum_dict_keys
from pyterpol3.synthetic.auxiliary import ZERO_TOLERANCE
from pyterpol3.plotting.plotting import *

# repeat userwarnings
warnings.simplefilter('always', UserWarning)

class Interface(object):
    """
    """
    def __init__(self, sl=None, rl=None, ol=None, fitter=None, debug=False,
                 adaptive_resolution=True, spectrum_by_spectrum=None,
                 log_iterations=False):
        """
        :param sl: StarList type
        :param rl: RegionList type
        :param ol: ObservedList type
        :param fitter
        :param debug
        :param adaptive_resolution - this (sounds better than it actually is)
                just means that resolution of the grid is set to twice
                the resolution of the spectrum with highest resolution
        :return:
        """

        # StarList is deepcopied by value, because
        # it is adjusted by the Interface
        if sl is not None:
            self.sl = sl.copy()
        else:
            self.sl = None

        # RegionList and the ObservedList are copied
        # by reference
        self.rl = rl
        self.ol = ol
        self.synthetics = {}
        self.grids = {}
        self.fitter = fitter
        self.spectrum_by_spectrum = spectrum_by_spectrum

        # debug mode
        self.debug = debug

        # define empty comparison list
        self.comparisonList = None

        # parameters that cannot be obatined through interpolation
        self._not_given_by_grid = ['lr', 'rv', 'vrot']

        # relation between rv_groups and regions
        self.rel_rvgroup_region = {}

        # properties of synthetic spectra
        self._synthetic_spectrum_kwargs = dict(step=0.01, order=4, padding=20.)

        # properties of grids
        self._grid_kwargs = dict(mode='default', debug=debug)

        # initialization of various boolean variables
        self.grid_properties_passed = False
        self.fit_is_running = False
        self.adaptive_resolution = adaptive_resolution
        self.log_iterations = log_iterations

        # temporary variable for info on the fitted parameters
        self.ident_fitted_pars = None
        self.one4all = False

    def __str__(self):
        """
        String representation of the class
        :return:
        """
        string = ""
        for attr, name in zip(['sl', 'rl', 'ol', 'fitter'], ['StarList', 'RegionList', 'ObservedList', 'Fitter']):
            string += '%s%s\n' % (name[:len(name)//2].rjust(50, '='), name[len(name)//2:].ljust(50, '='))
            string += str(getattr(self, attr))
        string += ''.ljust(100, '=')

        return string

    def accept_fit(self):
        """
        Propagates the fitting result to the class.
        :return:
        """

        # this should be done more carefully
        final_pars = self.fitter.result
        print("FINAL PARAMETERS:", final_pars)

        # list fitted parameters
        fitparams = self.get_fitted_parameters()

        # updates the parameters with the result
        for i in range(0, len(final_pars)):
            fitparams[i]['value'] = final_pars[i]

        # update the fitter with new initial parameters
        self.fitter.par0 = copy.deepcopy(final_pars)

    def add_comparison(self, region=None, parameters={}, observed=None, groups={}):
        """
        :param region the name of the corresponding region
        :param parameters a dictionary of the parameters required for the synthetic
                            spectrum
        :param observed the observed spectrum
        :param groups

        Add a record to the comparisonList
        :return: None

        """
        if self.debug:
            print('Settting comparison for region: %s \n groups: %s. \n parameters: %s' % \
                  (str(region), str(groups), str(parameters)))

        if self.comparisonList is None:
            raise Exception('The comparisonList has not been defined yet. Use Inteface.ready_comparison for that.')
        else:
            # pass the regions
            wmin = self.rl.mainList[region]['wmin']
            wmax = self.rl.mainList[region]['wmax']

            # try to read out the observed spectrum - everything
            if observed is not None:
                try:
                    ow, oi, oe = observed.get_spectrum(wmin, wmax)
                except:
                    # if it does not work out..
                    ow = observed.get_spectrum(wmin, wmax)
                    oi = None
                    oe = None


            self.comparisonList.append(dict(region=region,
                                            parameters=parameters,
                                            observed=observed,
                                            groups=groups,
                                            synthetic={x: None for x in list(parameters.keys())},
                                            chi2=0.0,
                                            wmin=wmin,
                                            wmax=wmax,
                                            wave=ow,
                                            intens=oi,
                                            error=oe
                                            )
                                       )

    def clear_all(self):
        """
        Clears the class.
        :return:
        """
        self.comparisonList = None
        self.grids = {}
        self.ol = None
        self.rl = None
        self.sl = None
        self.fitter = None
        self.synthetics = {}
        self._grid_kwargs = {}
        self._synthetic_spectrum_kwargs = {}
        self.rel_rvgroup_region = {}
        self.grid_properties_passed = False
        self.ident_fitted_pars = None

    def compute_chi2(self, pars=[], l=None, verbose=False):
        """
        :param pars:
        :param l
        :param verbose
        :return: chi square
        """
        if l is None:
            l = self.comparisonList

        # accounts for cases when we just evaluate current chi^2
        if len(pars) == 0:
            pars = self.get_fitted_parameters(attribute='value')

        # propagate the parameters to the
        # parameterlist and update it
        self.propagate_and_update_parameters(l, pars)

        # reads out the chi_2 from individual spectra
        chi2 = self.read_chi2_from_comparisons(l, verbose)

        # if we are fitting we store the info on the parameters
        if self.fit_is_running & self.log_iterations:
            self.fitter.append_iteration(dict(parameters=copy.deepcopy(pars), chi2=chi2))
        else:
            self.fitter.iter_number += 1

        # print every hundredth iteration
        if self.debug:
            print('Computed model: %s chi2: %s' % (str(pars), str(chi2)))
        else:
            if (self.fitter.iter_number+1) % 100 == 0:
                print('Computed model: %s chi2: %s' % (str(pars), str(chi2)))

        return chi2

    def compute_chi2_treshold(self, l=None, alpha=0.67):
        """
        Computes confidence level from normallized chi^2.
        It is of course not correct, but what can be done,
        when the model is evidently incorrect??
        :param l the list of comparisons
        :param alpha the chi-square treshold
        :return:
        """

        # use in-built comparison list of
        # no other was passed
        if l is None:
            l = self.comparisonList

        # get the degrees of freedom
        ddof = self.get_degrees_of_freedom(l)

        # estimate confidence limits
        chi2 = stats.chi2(ddof)
        vmin, vmax = chi2.interval(alpha)

        # now get vthe maximal value relative
        # to the minimal - minimal value is
        # what we get with the minimization
        # ratio = vmax/vmin
        diff = vmax-vmin
        # return ratio
        return diff

    def change_observed_list(self, ol):
        """
        Removes the old observe list and adds a new one.
        It also resets the group assignment between
        regions a and radial velocity groups. Each
        observed spectrum should have a rv group
        assigned. Otherwise the outcome might be
        wrong.
        :param ol:
        :return:
        """

        if self.ol is None:
            warnings.warn('There was no ObservedList attached to the Interface. Correct?')
        else:
            self.ol.clear_all()

        # attach new observed list
        self.ol = ol

        # reset the rv-group settings
        self._setup_rv_groups()

    def copy(self):
        """
        Creates a copy of self.
        :return:
        """

        other = Interface()
        for attr in ['ol', 'sl', 'rl', 'fitter', 'spectrum_by_spectrum',
                     'adaptive_resolution', 'debug', '_grid_kwargs',
                     '_synthetic_spectrum_kwargs']:
            v = copy.deepcopy(getattr(self, attr))
            setattr(other, attr, v)

        return other

    def choose_fitter(self, *args, **kwargs):
        """
        Just wrapper for the Fitter.choose_fitter method
        see parameter descriptio there.
        :param args:
        :param kwargs:
        :return:
        """
        # fitter is rather simple, so if there is none set, we set an empty
        # one
        if self.fitter is None:
            self.fitter = Fitter(debug=self.debug)

        # select fitted parameters
        if 'fitparams' not in list(kwargs.keys()):
            fitparams = self.get_fitted_parameters()
            kwargs['fitparams'] = fitparams

        self.fitter.choose_fitter(*args, **kwargs)

    def draw_random_sample(self):
        """
        Takes a random sample from the data. This random sample
        contains the same name of observations as the original
        one -- i.e. some observations repeat within the sample.
        :return:
        """

        # get number of observations
        nobs = len(self.ol)

        # take original spectra and groups
        rv_groups = self.ol.observedSpectraList['group']['rv']
        spectra = self.ol.observedSpectraList['spectrum']

        # make random data sample
        ind = np.sort(np.random.randint(nobs, size=nobs))
        random_rv_groups = [rv_groups[i] for i in ind]
        random_spectra = [spectra[i] for i in ind]

        # reset group numbers
        newobs = []
        for i in range(0, len(random_spectra)):
            newobs.append(dict(filename=random_spectra[i].filename,
                               error=random_spectra[i].global_error,
                               group=dict(rv=i),
                               hjd=random_spectra[i].hjd),
                          )

        # create new list of observations
        ol = ObservedList()
        ol.add_observations(newobs)

        # copy the starlist
        sl_new = self.sl.copy()

        for i, rndg in enumerate(random_rv_groups):
            pars = self.sl.get_parameter(rv=rndg)
            for c in self.sl.get_components():
                sl_new.set_parameter(name='rv', component=c, group=i, value=pars[c][0].value)

        # get regions
        rl = self.rl

        # create bew Interface
        itf = Interface(sl=sl_new, rl=rl, ol=ol)

        # set attributes
        setattr(itf, 'grids', self.grids)
        setattr(itf, 'synthetics', self.synthetics)
        setattr(itf, '_grid_kwargs', self._grid_kwargs)
        setattr(itf, '_synthetic_spectrum_kwargs', self._synthetic_spectrum_kwargs)
        setattr(itf, 'fitter', self.fitter)
        setattr(itf, 'adaptive_resolution', self.adaptive_resolution)
        setattr(itf, 'debug', self.debug)

        # finalize
        itf._setup_rv_groups()
        itf.ready_comparisons()
        itf.populate_comparisons()

        return itf

    @staticmethod
    def extract_parameters(l, attr='value'):
        """
        Converts a list of parameter class to a
        dictionary.
        :param l
        :param attr
        :return:
        """
        params = {par['name']: par[attr] for par in l}
        return params

    @staticmethod
    def evaluate_mcmc(f=None, treshold=100):
        """
        Returns best-fit values and errors estimated from the convergence.
        :param f: mcmc log
        :param treshold
        :return:
        """

        # read the fitlog
        log, nwalkers, niter, npars = read_mc_chain(f)

        # take only data, where the mcmc, has burnt in
        log['data'] = log['data'][nwalkers*treshold:,:]

        # best result
        minind = np.argmin(-log['data'][:, -1])

        # outputlist of errors
        errors = {}

        # fill the dictionary with errors
        for i in range(0, len(log['component'])):

            # parameter component, group
            p = log['name'][i]
            c = log['component'][i]
            g = log['group'][i]

            if c not in list(errors.keys()):
                errors[c] = {}
            if p not in list(errors[c].keys()):
                errors[c][p] = []

            # get the error estimate
            best = log['data'][minind, i]
            lower = log['data'][:, i].min() - best
            upper = log['data'][:, i].max() - best
            gauss_mean = log['data'][:, i].mean()
            gauss_sigma = log['data'][:, i].std(ddof=1)

            # append the value
            errors[c][p].append(dict(best=best, group=g, gauss_mean=gauss_mean,
                                     gauss_sigma=gauss_sigma, lower=lower, upper=upper))

        return errors


    def get_comparisons(self, verbose=False, **kwargs):
        """
        Narrows down the number of comparisons.
        :param verbose return indices in the original list
        :param kwargs parameters according to the comparison list will be narrowed down
        :return:
        """
        # empty arrays for the output
        clist = []
        indices = []

        # parameter keys
        keys = list(kwargs.keys())

        # go over each recordd within list of comparisons
        for i in range(0, len(self.comparisonList)):

            # the keys that we test are somewhat heterogeneous
            # thsi construction is not pretty.
            include = True
            for key in keys:
                # print key
                # what if the key lies
                if key in list(self.comparisonList[i]['groups'].keys()) \
                        and (kwargs[key] != self.comparisonList[i]['groups'][key]):
                    include = False
                    break
                if hasattr(self.comparisonList[i]['observed'], key) and \
                                self.comparisonList[i]['observed'].key != kwargs[key]:
                    include = False
                    break
                if key == 'region' and self.comparisonList[i]['region'] != kwargs[key]:
                    include = False
                    break

            # if it survived all tests it is included
            if include:
                clist.append(self.comparisonList[i])
                indices.append(i)

        # if we want to get indices of the found in the original array
        if verbose:
            return clist, indices
        else:
            return clist

    def get_defined_groups(self, component=None, parameter=None):
        """
        Returns a dictionary of defined groups
        :param component:
        :param parameter:
        :return:
        """

        return self.sl.get_defined_groups(component=component, parameter=parameter)

    def get_degrees_of_freedom(self, l=None):
        """
        Computes degrees of freadom for a given comparison list
        :param l:
        :return: number of degrees of freedom
        """

        if l is None:
            l = self.comparisonList

        # number of fitted parameters
        m = len(self.get_fitted_parameters())

        n = 0
        # number of fitted spectra points
        for rec in l:
            for c in list(rec['synthetic'].keys()):
                n += len(rec['synthetic'][c])

        return n-m

    def get_fitted_parameters(self, attribute=None):
        """
        lists all fitted Parameters or a list of one
        of their attributes
        :param
        :return:
        """

        # return the list of Parameters
        if attribute is None:
            return self.sl.get_fitted_parameters()
        else:
            return [par[attribute] for par in self.sl.get_fitted_parameters()]

    def get_observed_spectra_number(self):
        """
        :return:
        """

        if self.ol is not None:
            return len(self.ol)
        else:
            return 0

    def get_observed_spectrum(self, filename=None):
        """
        Returns observed spectrum accoreding to its name.
        :param filename name of the querried spectrum
        :return:
        """
        return self.ol.get_spectra(filename=filename)[0]

    def list_comparisons(self, l=None):
        """
        This function displays all comparisons.
        :param l list of comparisons
        :return: string
        """
        if l is None:
            l = self.comparisonList

        string = ''
        for i, rec in enumerate(l):
            string += "========================= Comparison %s =========================\n" % str(i).zfill(3)
            reg = rec['region']
            # list region
            string += 'region: %s:(%s,%s)\n' % (reg, str(self.rl.mainList[reg]['wmin']),
                                                str(self.rl.mainList[reg]['wmax']))

            # list observed spectrum
            if rec['observed'] is not None:
                string += "observed: %s\n" % rec['observed'].filename
            else:
                string += "observed: NONE\n"

            # lists all parameters
            for c in list(rec['parameters'].keys()):
                string += 'component: %s ' % c
                # print rec['parameters'][c]
                for par in rec['parameters'][c]:
                    string += "%s: %s " % (par['name'], str(par['value']))
                string += '\n'

            # list all groups
            string += 'groups: %s\n' % str(rec['groups'])
            string += 'chi2: %s\n' % str(rec['chi2'])
        string += "==================================================================\n"

        return string

    def list_fitters(self):
        """
        Lists all available fitters.
        :return:
        """

        if self.fitter is not None:
            return self.fitter.list_fitters()
        else:
            raise AttributeError('No fitter has been attached yet.')

    @staticmethod
    def load(f, one4all=False):
        """
        Loads the type from a file created with the save method.
        :param f: the loaded file
        :return:
        """
        # first load the interface

        # read the file
        lines = read_text_file(f)
        data_start = len(lines)
        for i, l in enumerate(lines):
            if l.find('INTERFACE') > -1:
                data_start = i
                break

        # check that there are actually some data in the file
        # the algorithm failed to load the class
        if data_start >= len(lines):
            warnings.warn('No interface was found was found.')
            return False

        # dictionary for the Interface attributes
        ddicts = {}
        for l in lines[1:]:
            d = l.split()
            # once we reach arain the Interface, we end
            if l.find('INTERFACE') > -1:
                break

            # define record names and types
            dnames = dict(
                grid_parameters=['mode'],
                synthetic_spectra_parameters=['order', 'step', 'padding'],
                env_keys=['debug', 'adaptive_resolution']
            )

            dtypes = dict(
                grid_parameters=[str],
                synthetic_spectra_parameters=[int, float, float],
                env_keys=[string2bool, string2bool]
            )
            # load all keys - env_vars, grid and synthetic spectra parameters
            for dname in list(dnames.keys()):
                if d[0].find(dname) > -1:
                    # print d[0]
                    p = dnames[dname]
                    pt = dtypes[dname]
                    ddict = {d[i].strip(':'): d[i+1] for i in range(1, len(d), 2)}
                    # cast the variables to correct type
                    for k in list(ddict.keys()):
                        i = p.index(k)
                        ddict[k] = pt[i](ddict[k])
                    # print ddict
                    ddicts[dname] = ddict
                    # print ddicts

        # load the remaining data
        rl = RegionList()
        # print rl.load(f)
        if not rl.load(f):
            raise ValueError('No records on the RegionList were found in %s.' % f)
        sl = StarList()
        if not sl.load(f):
            raise ValueError('No records on the StarList were found in %s.' % f)
        fitter = Fitter()
        if not fitter.load(f):
            warnings.warn('No fitter was found in file %s' % f)
            fitter = None
        ol = ObservedList()
        if not ol.load(f):
            warnings.warn('No ObservedList was found in file %s' % f)
            ol = None

        # print ddicts
        # print fitter
        # setup the interface
        itf = Interface(sl=sl, ol=ol, rl=rl, fitter=fitter, **ddicts['env_keys'])
        itf.set_one_for_all(one4all)
        gpars = {}

        # print ddicts
        # merge grid ans synthetic spectra parameters
        for d in [ddicts['synthetic_spectra_parameters'], ddicts['grid_parameters']]:
            for k in list(d.keys()):
                gpars[k] = d[k]
        itf.set_grid_properties(**gpars)

        itf.setup()
        itf.populate_comparisons()

        # self.choose_fitter(self.fitter.fittername)

        # if we got here, we loaded the data
        return itf

    def populate_comparisons(self, l=None, demand_errors=False):
        """
        Creates a synthetic spectrum for every record in
        the comparisonList.
        :param l
        :param demand_errors
        :return:
        """
        if l is None:
            l = self.comparisonList
        # go over ech comparison in the list
        for rec in l:
            # get the region
            region = rec['region']

            # get the intensity and error
            error = rec['error']
            intens = rec['intens']

            # go over each component
            for c in list(rec['parameters'].keys()):
                pars = self.extract_parameters(rec['parameters'][c])

                # use only those parameters that are not constrained with the grid
                pars = {x: pars[x] for x in list(pars.keys()) if x in self._not_given_by_grid}

                # populate with the intensity vector of each component
                if rec['observed'] is not None:
                    if demand_errors and rec['error'] is None:
                        raise ValueError('It is not allowed to call chi-square without having'
                                         ' uncertainties set.')

                    # extract the wavelength
                    wave = rec['wave']

                    # get the instrumental broadening
                    fwhm = rec['observed'].get_instrumental_width()

                    # define korelmode
                    korelmode = rec['observed'].korel

                    # generate the synthetic spectrum
                    rec['synthetic'][c] = self.synthetics[region][c].get_spectrum(wave=wave,
                                                                                  only_intensity=True,
                                                                                  korel=korelmode,
                                                                                  fwhm=fwhm,
                                                                                  **pars)
                else:
                    wmin = rec['wmin']
                    wmax = rec['wmax']
                    error = None
                    korelmode = False
                    rec['synthetic'][c] = self.synthetics[region][c].get_spectrum(wmin=wmin,
                                                                                  wmax=wmax,
                                                                                  only_intensity=True,
                                                                                  korel=korelmode,
                                                                                  **pars)

            # it is mandatory to provide errors for
            # computation of the chi2
            if error is not None:
                # sum component spectra
                for i, c in enumerate(rec['synthetic'].keys()):
                    if i == 0:
                        syn = rec['synthetic'][c].copy()
                    else:
                        syn = syn + rec['synthetic'][c]

                # setup the chi2
                rec['chi2'] = np.sum(((intens - syn) / error) ** 2)

    def optimize_rv(self, fitter_name=None, groups=None, **fitter_kwargs):
        """
        Optimizes radial velocities spectrum by spectrum.
        :return:
        """
        # turn off fitting of all parameters
        for p in self.sl.get_parameter_types():
            self.set_parameter(parname=p, fitted=False)

        # if not defined, get rv groups
        if groups is None:
            groups = self.get_defined_groups(parameter='rv')
            groups_list = []
            for c in list(groups.keys()):
                groups_list.extend(groups[c]['rv'])

            # rename back and make unique
            groups = np.unique(groups_list)

        # choose fitter
        if fitter_name is not None:
            self.choose_fitter(fitter_name, **fitter_kwargs)

        # iterate over groups
        for g in groups:
            self.set_parameter(parname='rv', group=g, fitted=True)
            l = self.get_comparisons(rv=g)
            self.run_fit(l=l)
            self.set_parameter(parname='rv', group=g, fitted=False)

    def plot_all_comparisons(self, l=None, savefig=False, figname=None):
        """
        Creates a plot of all setup comparisons.
        :param l
        :param savefig
        :param figname
        :return: None
        """
        if figname is not None:
            savefig = True

        if l is None:
            l = self.comparisonList
        if len(l) == 0:
            raise ValueError('The comparison list is empty. Did you run interface.setup() and interface.populate()?')
        for i in range(0, len(l)):
            self.plot_comparison_by_index(i, l=l, savefig=savefig, figname=figname)

    def plot_comparison_by_index(self, index, l=None, savefig=False, figname=None):
        """
        :param index
        :param l
        :param savefig
        :param figname
        :return:
        """

        # the comparison
        if l is None:
            cpr = self.comparisonList[index]
        else:
            cpr = l[index]

        # boundaries
        reg = cpr['region']
        wmin = self.rl.mainList[reg]['wmin']
        wmax = self.rl.mainList[reg]['wmax']

        # merge the spectra
        if any([cpr['synthetic'][key] is None for key in list(cpr['synthetic'].keys())]):
            raise ValueError('The synthetic spectra are not computed. Did you run Interface.populate_comparisons()?')
        si = sum_dict_keys(cpr['synthetic'])

        # names
        if cpr['observed'] is not None:
            obsname = cpr['observed'].filename.split('/')[-1]
        else:
            obsname = 'NONE'
        synname = ''
        for c in cpr['parameters']:
            synname += 'Component: %s ' % c
            pdict = self.extract_parameters(cpr['parameters'][c])
            synname += str({k: "%.4f" % pdict[k] for k in list(pdict.keys())}) + '\n'

        if cpr['observed'] is not None:
            try:
                w, oi, ei = cpr['observed'].get_spectrum(wmin, wmax)
            except:
                w, oi, = cpr['observed'].get_spectrum(wmin, wmax)
                ei = np.zeros(len(w))
                warnings.warn('Your data observed spectrum: %s has not errors attached!')
        else:
            w = np.linspace(wmin, wmax, len(si))

        if figname is None:
            figname = "_".join([obsname, 'wmin', str(int(wmin)), 'wmax', str(int(wmax))]) + '.png'
        else:
            figname = "_".join([figname, obsname, 'wmin', str(int(wmin)), 'wmax', str(int(wmax))]) + '.png'
            savefig = True

        if self.debug:
            print("Plotting comparison: observed: %s" % obsname)
            print("Plotting comparison: synthetics: %s" % synname)

        # do the plot
        fig = plt.figure(figsize=(16, 10), dpi=100)
        ax = fig.add_subplot(211)

        if cpr['observed'] is not None:
            ax.errorbar(w, oi, yerr=ei, fmt='-', color='k', label=obsname)
        ax.plot(w, si, 'r-', label=synname)
        ax.set_xlim(wmin, wmax)
        ax.set_ylim(0.95*si.min(), 1.05*si.max())
        ax.set_xlabel('$\lambda(\AA)$')
        ax.set_ylabel('$F_{\lambda}$(rel.)')
        ax.legend(fontsize=8, fancybox=True, shadow=True, bbox_to_anchor=(1.0, 1.2))

        if cpr['observed'] is not None:
            ax = fig.add_subplot(212)
            resid = oi-si
            ax.plot(w, resid, 'y', label='residuals')
            ax.set_xlabel('$\lambda(\AA)$')
            ax.set_ylabel('$F_{\lambda}$(rel.)')
            ax.set_xlim(wmin, wmax)
            ax.set_ylim(0.95*resid.min(), 1.05*resid.max())
            ax.legend(fontsize=8, loc=3)

        # save the figure
        if savefig:
            plt.savefig(figname)
            plt.close(fig)
            res = oi-si
            # save the resulting graphical comparison # S
            with open(figname + '_values.txt', 'w') as tabular: # S
                tabular.write("#%17s%21s%23s%21s" % ('wavelength [Ang]', 'fit flux (rel.)', 'measured flux (rel.)', 'meas-fit (rel.)') + '\n') # S
                for i in range(len(w)): # S
                    tabular.write("%18s%21s%23s%21s" % (w[i], si[i], oi[i], res[i].round(16))) # S
                    tabular.write('\n') # S



    def plot_convergence(self, f=None, parameter='chi2', component='all', group='all', savefig=True, figname=None):
        """
        Plots convergence of the chi2 and parameters.
        :param f
        :param parameter
        :param component
        :param group
        :param savefig
        :param figname
        :return:
        """
        if f is None:
            f = self.fitter.fitlog

        if figname is not None:
            savefig = True

        # read the log
        log = read_fitlog(f)

        block = []
        labels = []
        # set the plotted parameters
        if parameter.lower() == 'all':
            parameters = np.unique(log['name'])
        else:
            parameters = [parameter]

        if component.lower() == 'all':
            components = np.unique(log['component'])
        else:
            components = [component]

        if group.lower() == 'all':
            groups = np.unique(log['group'])
        else:
            groups = [group]

        # select those mathcing the choice
        i = 0
        for p, c, g in zip(log['name'], log['component'], log['group']):

            if p not in parameters:
                i += 1
                continue
            elif c not in components:
                i += 1
                continue
            elif g not in groups:
                i += 1
                continue
            else:
                label = '_'.join(['p', p, 'c', c, 'g', str(g)])
                labels.append(label)
                block.append(log['data'][:, i])
                i += 1

        # append chi_square
        if (parameter.lower() in ['chi2']) | (parameter == 'all'):
            block.append(log['data'][:, -1])
            labels.append('chi2')

        # print labels
        plot_convergence(np.column_stack(block), labels, figname=figname, savefig=savefig)

    @staticmethod
    def plot_convergence_mcmc(f='chain.dat', parameters='all', components='all', groups='all',
                              savefig=True, figname=None):
        """
        Plots convergence of a mcmc_chain
        :param f:
        :param parameters:
        :param components:
        :param groups:
        :param savefig:
        :param figname:
        :return:
        """

        # load data
        log, nwalkers, niter, npars = read_mc_chain(f)

        # set the plotted parameters
        if parameters == 'all':
            parameters = np.unique(log['name'])
        if components == 'all':
            components = np.unique(log['component'])
        if groups == 'all':
            groups = np.unique(log['group'])

        if any([isinstance(x, (float, int, str)) for x in [components, parameters, groups]]):
            raise TypeError('Parameters (parameter, component, group) have to be either type list'
                            ' or string == \'all\'.')

        # an array for empty indices.
        indices = []
        labels = []

        i = 0
        # fill the array of indices
        for p, c, g in zip(log['name'], log['component'], log['group']):
            # do only the desired ones
            for v, vals in zip([p, c, g], [parameters, components, groups]):
                # print v, vals
                if v not in vals:
                    i += 1
                    break
            indices.append(i)
            labels.append('_'.join(['c', c, 'p', p, 'g', str(g)]))
            i += 1

        # do the plot
        # print len(indices), len(labels)
        plot_walkers(log['data'], niter, nwalkers, indices=indices,
                     labels=labels, savefig=savefig, figname=figname)

    @staticmethod
    def plot_covariances_mcmc(f='chain.dat', l=None, treshold=100, parameters=None,
                            components=None, groups=None, nbin=20, savefig=True, figname=None):
        """
        Plots covariances between selected parameters
        :param f
        :param l
        :param treshold
        :param parameters
        :param components
        :param groups
        :param nbin
        :param savefig
        :param figname
        :return:
        """
        if figname is not None:
            savefig = True

        # reads the chan
        log, nwalkers, niter, npars = read_mc_chain(f)

        # set the plotted parameters
        if parameters is None:
            parameters = np.unique(log['name'])
        if components is None:
            components = np.unique(log['component'])
        if groups is None:
            groups = np.unique(log['group'])

        if any([isinstance(x, (float, int, str)) for x in [components, parameters, groups]]):
            raise TypeError('Parameters (parameter, component, group) have to be either type list'
                            ' or string == \'all\'.')

        # take only the part, where the sampler is burnt in
        log['data'] = log['data'][nwalkers*treshold:,:]

        # select those matching the choice
        indices = []
        labels = []

        i = 0
        # fill the array of indices
        for p, c, g in zip(log['name'], log['component'], log['group']):

            # do only the desired ones
            saveind = True
            for v, vals in zip([p, c, g], [parameters, components, groups]):
                if v not in vals:
                    saveind = False
                    break

            if saveind:
                indices.append(i)
                labels.append('_'.join(['c', c, 'p', p, 'g', str(g)]))
            i += 1

        # do the corner plot
        corner.corner(log['data'][:,indices], bins=nbin, labels=labels,
                      quantiles=(0.67*np.ones(len(indices))).tolist(),
                      truths=(np.zeros(len(indices))).tolist()
                      )

        # save the figure
        if savefig:
            if figname is None:
                figname = 'correlations.png'
            plt.savefig(figname)

    @staticmethod
    def plot_variances_mcmc(f=None, l=None, parameters=None, components=None, groups=None, nbin=20,
                         treshold=100, savefig=True, figname=None):
        """
        Plots covariances between selected parameters
        :param f
        :param l
        :param treshold
        :param parameters
        :param components
        :param groups
        :param nbin
        :param savefig
        :param fignamez
        :return:
        """
        if any([isinstance(x, (float, int, str)) for x in [components, parameters, groups]]):
            raise TypeError('Parameters (parameter, component, group) have to be either type list'
                            ' or string == \'all\'.')

        if figname is not None:
            savefig = True

        # reads the chan
        log, nwalkers, niter, npars = read_mc_chain(f)

        # set the plotted parameters
        if parameters is None:
            parameters = np.unique(log['name'])
        if components is None:
            components = np.unique(log['component'])
        if groups is None:
            groups = np.unique(log['group'])

        # take only the part, where the sampler is burnt in
        log['data'] = log['data'][nwalkers*treshold:,:]

        # select those mathcing the choice
        npar = len(log['name'])
        for i in range(1, npar):
            for j in range(0, i):

                # extract individual values
                p1 = log['name'][i]
                c1 = log['component'][i]
                g1 = log['group'][i]

                # end if there are no components matching our
                # choice of components, groups and parameters
                if any([p.lower() not in parameters for p in [p1]]):
                    continue
                if any([c.lower() not in components for c in [c1]]):
                    continue
                if any([g not in groups for g in [g1]]):
                    continue

                # setup labels
                label1 = '_'.join(['p', p1, 'c', c1, 'g', str(g1).zfill(2)])

                # setup plotted data
                x = log['data'][:, i]

                # do the oplot
                plot_variance(x,nbin=nbin, label=label1, savefig=savefig, figname=figname)

    def propagate_and_update_parameters(self, l, pars):
        """
        :param l
        :param pars
        :return:
        """

        # parameters are passed by reference, so
        # this should also change the starlist
        # and corresponding
        fitpars = self.sl.get_fitted_parameters()
        if len(pars) != len(fitpars):
            raise ValueError('Length of the vector passed with the fitting environment does '
                             'mot match length of the parameters marked as fitted.')

        for i, v in enumerate(pars):
            fitpars[i]['value'] = v

        # we have to recompute the synthetic spectra
        # if one grid parameter was passed
        # first check for which parameters
        # the grid parameters are fitted
        components_to_update = []

        for c in list(self.sl.fitted_types.keys()):
            for rec in self.sl.fitted_types[c]:

                # recompute only those components for those
                # grid parameter is fitted
                if rec not in self._not_given_by_grid:
                    components_to_update.append(c)

        # update the synthetic spectra
        if len(components_to_update) > 0:
            self.ready_synthetic_spectra(complist=components_to_update)

        # populate the comparison
        self.populate_comparisons(l=l, demand_errors=True)

    def ready_synthetic_spectra(self, complist=[]):
        """
        Readies the synthetic spectra for each region.
        :param complist list of components that will be re-computed,
        :return:
        """
        # if there is no list of components
        # for which to set the synthetic
        # parameters
        if len(complist) == 0:
            complist = self.sl.get_components()

        # regime in which we use one long spectrum
        if self.one4all:
            wl = self.rl.get_wavelengths()
            wmin = np.min(wl)
            wmax = np.max(wl)


        for reg in self.rl._registered_regions:
            # add the region to synthetics
            if reg not in list(self.synthetics.keys()):
                self.synthetics[reg] = dict()

            # wavelength_boundaries
            if not self.one4all:
                wmin = self.rl.mainList[reg]['wmin']
                wmax = self.rl.mainList[reg]['wmax']

            # get all parameters for a given region
            reg_groups = self.rl.mainList[reg]['groups'][0]
            reg_groups = {x: reg_groups[x] for x in list(reg_groups.keys())
                          if x not in self._not_given_by_grid}
            grid_pars = [x for x in self.sl.get_physical_parameters()
                         if x not in self._not_given_by_grid]

            # setup default groups - ie zero
            for par in grid_pars:
                if par not in list(reg_groups.keys()):
                    reg_groups[par] = 0

            # get list of Parameters
            parlist = self.sl.get_parameter(**reg_groups)

            for c in complist:
                # convert Parameter list to dictionary
                params = self.extract_parameters(parlist[c])
                # print params

                # padding has to be relatively large, since
                # we do not know what the rvs will be
                if self.debug:
                    print("Creating SyntheticSpectrum: params: %s wmin: %s wmax: %s" % (str(params),
                                                                                        str(wmin),
                                                                                        str(wmax)))

                if not self.one4all:
                    self.synthetics[reg][c] = self.grids[reg].get_synthetic_spectrum(params,
                                                                                 np.array([wmin, wmax]),
                                                                                 **self._synthetic_spectrum_kwargs)
                else:
                    self.synthetics[reg][c] = self.grids['all'].get_synthetic_spectrum(params,
                                                                                 np.array([wmin, wmax]),
                                                                                 **self._synthetic_spectrum_kwargs)


    def read_chi2_from_comparisons(self, l=None, verbose=False):
        """
        Reads the chi-squares from the list.
        :param l:
        :return:
        """

        # work with the min comparisonList if no other
        # is provided
        if l is None:
            l = self.comparisonList

        chi2 = 0.0
        if verbose:
            chi2_detailed = []

        # read out the chi squares
        for i in range(0, len(l)):
            chi2 += l[i]['chi2']

            # if verbosity is desired a detailed chi-square
            # info on each region is returned
            if verbose:
                chi2_detailed.append(dict(chi2=l[i]['chi2'],
                                     region=self.rl.mainList[l[i]['region']],
                                     rv_group=l[i]['groups']['rv']))
        if verbose:
            return chi2, chi2_detailed
        else:
            return chi2

    def ready_comparisons(self):
        """
        This function creates a dictionary, which is one of the
        cornerstones of the class. It creates a list of all
        combinations of the parameters.
        :return:
        """

        # start a list of comparisons that will
        # be carried out with the given dataset
        self.comparisonList = []

        # go region by region
        for reg in list(self.rl.mainList.keys()):
            # fitted region
            wmin = self.rl.mainList[reg]['wmin']
            wmax = self.rl.mainList[reg]['wmax']

            # region-dfined groups and parameters
            reg_groups = copy.deepcopy(self.rl.mainList[reg]['groups'][0])
            phys_pars = [x for x in self.sl.get_physical_parameters() if x not in ['rv']]
            # print reg, phys_pars, reg_groups

            # if the group is not defined, it is zero
            for par in phys_pars:
                if par not in list(reg_groups.keys()):
                    reg_groups[par] = 0

            # create a list of unique rv groups
            rv_groups = self.sl.get_defined_groups(parameter='rv')
            rv_groups = [rv_groups[key]['rv'] for key in list(rv_groups.keys())]

            temp = []
            for row in rv_groups:
                temp.extend(row)
            rv_groups = np.unique(temp)

            for rv_group in rv_groups:

                # append rv_group to groups
                all_groups = copy.deepcopy(reg_groups)
                all_groups['rv'] = rv_group

                # append rv parameter to the remaining parameters
                # rv_pars = self.sl.get_parameter(rv=rv_group)

                # get unique set of parameters for a given group
                all_pars = self.sl.get_parameter(**all_groups)
                # for c in rv_pars.keys():
                #     all_pars[c].extend(rv_pars[c])

                if self.ol is not None:

                    if rv_group not in self.rel_rvgroup_region[reg]:
                        continue

                    # the wmin wmax is used to check again that
                    # we are in the correct region.
                    if self.debug:
                        print("Queried parameters in ready comparisons:", wmin, wmax, rv_group)
                    obs = self.ol.get_spectra(wmin=wmin, wmax=wmax, rv=rv_group)
                    if len(obs) == 0:
                        continue
                else:
                    obs = [None]

                # add the comparison for each observed spectrum
                # because in an unlikely event, when we fit the
                # same RVs for several spectra
                for o in obs:

                    # What if we are only generating spectra???
                    # If there are spectra attached we are
                    # comparing and thats it!!
                    if o is None:
                        c = 'all'
                    else:
                        c = o.component
                    if c != 'all':
                        temp_all_pars = {c: all_pars[c]}
                    else:
                        temp_all_pars = all_pars

                    self.add_comparison(region=reg,
                                        parameters=temp_all_pars,
                                        groups=all_groups,
                                        observed=o,
                                        )

    def ready_comparisons_spectrum_by_spectrum(self):
        """
        This function creates a dictionary, which is one of the
        cornerstones of the class. It creates a list of all
        combinations of the parameters.
        :return:
        """
        # print self
        # start a list of comparisons that will
        # be carried out with the given dataset
        self.comparisonList = []

        # go region by region
        for reg in list(self.rl.mainList.keys()):
            # fitted region
            wmin = self.rl.mainList[reg]['wmin']
            wmax = self.rl.mainList[reg]['wmax']

            # generate a dictionary of unique groups for each parameter
            unique_groups = {}
            # phys_pars = [par for par in self.sl.get_physical_parameters() if par not in ['lr']]
            phys_pars = self.sl.get_physical_parameters()
            for par in phys_pars:
                groups = self.sl.get_defined_groups(parameter=par)
                temp = []
                for c in list(groups.keys()):
                    print(groups[c][par])
                    temp.extend(groups[c][par])
                unique_groups[par] = np.unique(temp).tolist()

            # print unique_groups

            # position in the row of each parameter
            position = {key: 0 for key in list(unique_groups.keys())}
            keys = list(unique_groups.keys())
            # print position
            # print unique_groups

            # THIS IS PROBABLY THE MOST IDIOTIC WAY HOW TO GET
            # ALL COMBINATIONS BETWEEN RECORDS IN N DIFFERENT LISTS
            # SURPRISINGLY IT DOES NOT GENERATE REDUNDANT COMPARISONS
            # It iterates over the positions list until for each
            # record in the list position[i] == len(unique_groups[i])
            # both are dictionaries of course
            i = 0
            all_groups_list = []
            # while position[keys[-1]] >= len(unique_groups[keys[-1]])-1:
            while True:
                # append the current groups
                temp = {key: unique_groups[key][position[key]] for key in keys}
                all_groups_list.append(temp)

                # search until you find a list of lenght > 1 or till the end
                while i < len(keys) and (position[keys[i]] == len(unique_groups[keys[i]])-1):
                    i += 1
                # if end was reached - end
                if not i < len(keys):
                    break
                else:
                    # else increment the record and start over
                    position[keys[i]] += 1
                    for j in range(0, i):
                        position[keys[j]] = 0
                        i = 0

            # for rec in all_groups_list:
                # print rec

            for rec in all_groups_list:
                # get unique set of parameters for a given group
                all_pars = self.sl.get_parameter(**rec)

                if self.ol is not None:
                    # if rv_group not in self.rel_rvgroup_region[reg]:
                    #     continue

                    # the wmin wmax is used to check again that
                    # we are in the correct region.
                    obs = self.ol.get_spectra(wmin=wmin, wmax=wmax, permissive=True, **rec)
                    if len(obs) == 0:
                        continue
                else:
                    obs = [None]

                # add the comparison for each observed spectrum
                # because in an unlikely event, when we fit the
                # same RVs for several spectra
                for o in obs:

                    # What if we are only generating spectra???
                    # If there are spectra attached we are
                    # comparing and thats it!!
                    if o is None:
                        c = 'all'
                    else:
                        c = o.component
                    if c != 'all':
                        temp_all_pars = {c: all_pars[c]}
                    else:
                        temp_all_pars = all_pars

                    self.add_comparison(region=reg,
                                        parameters=temp_all_pars,
                                        groups=rec,
                                        observed=o,
                                        )

    def remove_parameter(self, component, parameter, group):
        """
        :param component: component for which the parameter is deleted
        :param parameter:deleted paramer
        :param group
        :return:
        """

        self.sl.remove_parameter(component, parameter, group)

    def run_fit(self, l=None, verbose=False):
        """
        Starts the fitting
        :param l:
        :param verbose:
        :return:
        """
        # update fitted parameters
        self.update_fitter()

        # set the identification of fitted parameters
        self.fitter.set_fit_properties(self.sl.get_fitted_parameters(True)[1])

        # this starts recording of each iteration chi2
        self.fit_is_running = True

        # runs the fitting
        self.fitter(self.compute_chi2, l, verbose)

        # copy the fit into the whole structure
        self.accept_fit()

        # writes the remaining iterations within the file
        self.fitter.flush_iters()

        # turn of the fitting
        self.fit_is_running = False

    def run_bootstrap(self, limits, outputname=None, decouple_rv=True, niter=100, sub_niter=3):
        """
        Runs bootstrap simulation to estimate the errors. The initial parameter set is chosen
        randomly in the vicinity of the solution that is stored within the Interface type.
        :param limits: format dict(component1=dict(rv=[low, high], teff=[low, high],..),
        component2=dict(..), ..), where the range in which the random number is
        (stored_value - low, stored_value + high).
        :param outputname: Prefix name for result of each bootstrap iteration.
        :param decouple_rv: Should the rvs be fitted separately from the remaining parameters?
        :param niter: Number of bootstrap iteration.
        :param sub_niter: Number of subiteration, where rv is fitted first and then the
        remaining parameters. This parameter is irrelevant for decouple_rv = False.
        :return:
        """

        # set outputname of each iteration
        if outputname is None:
            outputname = 'bootstrap'

        # niter samples are computed
        for i in range(niter):

            # create an interface with a random data sample
            itf = self.draw_random_sample()

            # set a random starting point within limits
            for c in list(limits.keys()):
                for p in list(limits[c].keys()):

                    # user supplied limits
                    bs_vmin = limits[c][p][0]
                    bs_vmax = limits[c][p][1]

                    # get all defined groups
                    groups = itf.get_defined_groups(component=c, parameter=p)[c][p]

                    # for each group set random starting point
                    for g in groups:
                        # for each group, parameter and component
                        # get value, minimal and maximal
                        par = itf.sl.get_parameter(**{p : g})[c][0]
                        value = par.value
                        vmin = par.vmin
                        vmax = par.vmax

                        # set boundaries where random number is drawn
                        llim = max([value - bs_vmin, vmin])
                        ulim = min([value + bs_vmax, vmax])

                        # draw the random number
                        rn = llim + (ulim - llim) * np.random.random()

                        # set it to parameter
                        par.value = rn
                        par.vmin = max([vmin, value - 2 * bs_vmin])
                        par.vmax = min([vmax, value + 2 * bs_vmax])

            # set outputname for one fit
            outputname_one_iter = '.'.join([outputname, str(i).zfill(3), 'sav'])

            # get list of fitted parameters      
            fitpars = {}
            for c in list(itf.sl.componentList.keys()):
                fitpars[c] = []
                for p in list(itf.sl.componentList[c].keys()):
                    for k in range(0, len(itf.sl.componentList[c][p])):
                        if itf.sl.componentList[c][p][k].fitted:
                            fitpars[c].append(p)
                            break
                #sys.exit(0)
            
            # now proceed with the fittingss
            itf.save('.'.join([outputname, 'initial', str(i).zfill(3), 'sav']))
            if decouple_rv:
                # do several iterations, fitting rv and remaining parameters
                for j in range(sub_niter):

                    # turn off fitting of radial velocity
                    itf.set_parameter(parname='rv', fitted=False)

                    # turn on remaining parameters
                    for c in list(fitpars.keys()):
                        for p in fitpars[c]:
                            itf.set_parameter(parname=p, component=c, fitted=True)

                    # run the fit - not radial velocities
                    itf.run_fit()
                    #print itf
                    #print itf.list_comparisons()
                    # itf.save('.'.join(['before_rv', str(i).zfill(3), str(j).zfill(2), 'sav']))

                    # run the fit - radial velocities
                    itf.optimize_rv()
                    #print itf
                    #print itf.list_comparisons()
                    # itf.save('.'.join(['after_rv', str(i).zfill(3), str(j).zfill(2), 'sav']))
            else:
                itf.run_fit()

            # save the result
            itf.save(outputname_one_iter)

    def run_mcmc(self, chain_file='chain.dat', nwalkers=None, niter=500, l=None, verbose=False):
        """
        Runs the mcmc error estimation.
        :return:
        """
        # pass on the fit properties
        self.fitter.set_fit_properties(self.sl.get_fitted_parameters(True)[1])

        # update the boundaries
        vmins = self.get_fitted_parameters(attribute='vmin')
        vmaxs = self.get_fitted_parameters(attribute='vmax')
        self.fitter.set_lower_boundary(vmins)
        self.fitter.set_upper_boundary(vmaxs)

        # get the values
        vals = self.get_fitted_parameters(attribute='value')

        # set up number of walkers
        if nwalkers is None:
            nwalkers = 4*len(vals)

        # run the mcmc sampling
        self.fitter.run_mcmc(self.compute_chi2, chain_file, vals, nwalkers, niter, l, verbose)

    def save(self, ofile):
        """

        Saves the interface as a text file.
        :param ofile: file or filehandler
        :return:
        """

        # open the file
        if isinstance(ofile, str):
            ofile = open(ofile, 'w')

        # Setup the interface variables first.
        string = ' INTERFACE '.rjust(105, '#').ljust(200, '#') + '\n'

        # set the grid properities
        string += 'grid_parameters: '
        for key in list(self._grid_kwargs.keys()):
            if key not in ['debug']:
                string += '%s: %s ' % (key, str(self._grid_kwargs[key]))
        string += '\n'

        # set the synthetic spectra parameters
        string += 'synthetic_spectra_parameters: '
        for key in list(self._synthetic_spectrum_kwargs.keys()):
            string += '%s: %s ' % (key, str(self._synthetic_spectrum_kwargs[key]))
        string += '\n'

        # Set the environmental keys
        enviromental_keys = ['adaptive_resolution', 'debug']
        string += 'env_keys: '
        for ekey in enviromental_keys:
            string += "%s: %s " % (ekey, str(getattr(self, ekey)))
        string += '\n'

        # finalize the string
        string += ' INTERFACE '.rjust(105, '#').ljust(200, '#') + '\n'
        ofile.writelines(string)

        # save the starlist
        self.sl.save(ofile)

        # save the fitter
        self.fitter.save(ofile)

        # save the regions
        self.rl.save(ofile)

        # save the observed list - if any was given
        # and compute the chi-square
        if self.ol is not None:

            # saves the observed list
            self.ol.save(ofile)

            # saves the chi-square and degrees of freedom
            string = ' CHI-SQUARE '.rjust(105, '#').ljust(200, '#') + '\n'

            # compute chi2 and ddof
            chi2 = self.compute_chi2()
            ddof = self.get_degrees_of_freedom()

            # save it within the asc file
            string += 'Chi^2: %s Degrees_Of_Freedom: %s Reduced Chi^2: %s\n' % \
                      (str(chi2), str(ddof), str(chi2 / ddof))
            string += ' CHI-SQUARE '.rjust(105, '#').ljust(200, '#') + '\n'
            ofile.writelines(string)

    def setup(self):
        """
        This function probes the observed and
        region list and propagates group definitions
        from them to the starlist.
        :return:
        """
        # first setup region groups
        if self.rl is not None:
            region_groups = self.rl.get_region_groups()
            self.sl.set_groups(region_groups)
        else:
            self.rl = RegionList(debug=self.debug)
            self.rl.get_regions_from_obs(copy.deepcopy(self.ol.observedSpectraList['spectrum']))

            # TODO setting up the region <-> rv relation better - this is a quick fix
            # TODO and unlikely a robust one
            self.rel_rvgroup_region = {reg: [0] for reg in self.rl.get_registered_regions()}
            region_groups = self.rl.get_region_groups()
            self.sl.set_groups(region_groups)

        # print self

        # setup radial velocity groups
        if self.ol is not None:
            # we will fit some parameters separately at some spectra
            # therefore all groups are assihgne dfrom the data, not only
            # the radial velocities
            # check that all fitted spectra fit within at least one
            # spectral region
            self.verify_spectra_and_regions()

            if self.spectrum_by_spectrum is not None:
                # setup groups for each spectrum
                # relative luminosity is given by spectra region, not the spectrum itself
                phys_pars = [par for par in self.sl.get_physical_parameters() if par not in 'lr']

                # parameters that will be owned by each spectrum
                varparams = self.spectrum_by_spectrum

                # common parameters
                fixparams = [par for par in phys_pars if par not in self.spectrum_by_spectrum]
                self._set_groups_to_observed(varparams, fixparams)
                self._setup_all_groups()
            else:
                # print self
                self._setup_rv_groups()
                # print self

            # setup the wavelength step of synthetic spectra
            # from observed psectra
            if self.adaptive_resolution:
                step = self.ol.get_resolution()

                if self.debug:
                    print("The step size of the grid is: %s Angstrom." % str(step/2.))
                self.set_grid_properties(step=step/2.)

        else:
            warnings.warn('There are no data attached, so all regions are set to '
                          'have the same radial velocity. Each component can have'
                          'different velocity of course.')

        # attach grids to the interface
        self._setup_grids()

        # create the basic interpolated spectra
        self.ready_synthetic_spectra()

        # setup all comparisons
        if self.spectrum_by_spectrum is not None:
            self.ready_comparisons_spectrum_by_spectrum()
        else:
            self.ready_comparisons()

        # setup fitter
        if self.fitter is None:
            self.fitter = Fitter(debug=self.debug)

        # at the end the comparisons synthetic spectra are populated
        self.populate_comparisons()

    def set_grid_properties(self, **kwargs):
        """
        :param kwargs: padding - number of spectra to use for
                padding of synthetic spectra
        :param kwargs: order - maximal number of spectra
                for interpolation
        :return:
        """
        # if we pass step, we turn off
        # adaptive resolution
        if 'step' in list(kwargs.keys()):
            self.adaptive_resolution = False

        for k in list(kwargs.keys()):
            # setup grid parameters
            if k in list(self._grid_kwargs.keys()):
                self._grid_kwargs[k] = kwargs[k]
            # setup synthetic spectra parameters
            elif k in list(self._synthetic_spectrum_kwargs.keys()):
                self._synthetic_spectrum_kwargs[k] = kwargs[k]
            else:
                raise KeyError('Key: %s is not a property of either the grid or synthetic spectra. '
                               'The only parameters adjustable with this function are: '
                               ' %s for grid and % for synthetic spectra.'
                               % (k,
                                  str(list(self._grid_kwargs.keys())),
                                  str(self._synthetic_spectrum_kwargs)))

    def _set_groups_to_observed(self, varparams, fixparams):
        """
        :param varparams parameters whose group number should vary from spectrum to spectrum
        :param fixparams parameters whose group should be the same for all spectra
        :return:
        """
        if self.ol is None:
            raise AttributeError('No data are attached.')
        else:
            for i in range(0, len(self.ol)):
                # setup varying parameters
                for vpar in varparams:
                    if vpar not in list(self.ol.observedSpectraList['group'].keys()):
                        self.ol.observedSpectraList['group'][vpar] = np.zeros(len(self.ol))
                    self.ol.observedSpectraList['group'][vpar][i] = i+1

                # setup fixed parameters
                for fpar in fixparams:
                    if fpar not in list(self.ol.observedSpectraList['group'].keys()):
                        self.ol.observedSpectraList['group'][fpar] = np.zeros(len(self.ol))
                    self.ol.observedSpectraList['group'][fpar][i] = 0

        # set the groups from table to spectra
        self.ol._set_groups_to_spectra()

    def set_one_for_all(self, switch):
        """
        Sets usage of one grid for all regions. This is faster.
        When we do not have lots of empty regions between fitted
        regions. It reduces number of spectra loading required
        but increases the duration of interpolation,
        :param switch turn on/off the fitting
        :return:
        """
        if not isinstance(switch, (bool, int)):
            raise TypeError('Switch of the one4all regime must have type bool.')

        self.one4all = switch
        self._setup_grids()

    def set_parameter(self, component='all', parname=None, group='all', **kwargs):
        """
        :param component:
        :param parname
        :param group:
        :param kwargs: keywords to be set up for each parameter
        :return:
        """

        # check the results
        if parname is None:
            print("I cannot adjust parameter: %s." % str(parname))
        if len(list(kwargs.keys())) == 0:
            return

        # setup the components
        if component == 'all':
            component = self.sl.get_components()
        else:
            component = [component]

        # create a list of unique groups if all are needed
        if group == 'all':
            groups = []
            dict_groups = self.sl.get_defined_groups(parameter=parname)
            for c in list(dict_groups.keys()):
                groups.extend(dict_groups[c][parname])
            groups = np.unique(groups)
        else:
            groups = [group]

        # propagate to the star
        for c in component:
            for g in groups:
                # print c, g, kwargs
                self.sl.set_parameter(parname, c, g, **kwargs)

        # print self
        # recompute synthetic spectra
        if (parname not in self._not_given_by_grid) & ('value' in list(kwargs.keys())):
            self.ready_synthetic_spectra()

        # update the fitter if number of fitted
        # parameters changes
        if 'fitted' in list(kwargs.keys()) and self.fitter.fittername is not None:
            fitparams = self.get_fitted_parameters()
            self.choose_fitter(name=self.fitter.fittername, fitparams=fitparams, **self.fitter.fit_kwargs)

    def set_error(self, parname='rv', component=None, error=1.0):
        """
        Sets error by adjusting vmin, vmax,
        :param parname: name of the parameter
        :paramn components
        :param error: the error, ehich will be used to set boundaries
        :return:
        """
        if component is not None:
            components = [component]
        else:
            components = self.sl._registered_components

        # get all fitted parameters
        parname = parname.lower()
        for c in components:
            if parname in list(self.sl.componentList[c].keys()):
                for p in self.sl.componentList[c][parname]:
                    v = p['value']

                    # relative luminosity needs special treatment
                    if p['name'] == 'lr':
                        p['vmin'] = max([0.0, v - error])
                        p['vmax'] = min([1.0, v + error])

                    # and so does also the rotational velocity
                    elif p['name'] == 'vrot':
                        p['vmin'] = max([0.0, v - error])
                        p['vmax'] = v + error

                    # and the rest is simple
                    else:
                        p['vmin'] = v - error
                        p['vmax'] = v + error

    def _setup_grids(self):
        """
        Initializes grid of synthetic spectra for each region -
        i.e. there is no point in calling the function without
        having the regions set up.

        :params kwargs -see pyterpol.
        :return:
        """
        if not self.one4all:
            for reg in list(self.rl.mainList.keys()):
                self.grids[reg] = SyntheticGrid(**self._grid_kwargs)
        else:
            # assume that there is only one grid for all
            self.grids['all'] = SyntheticGrid(**self._grid_kwargs)

    def _setup_rv_groups(self):
        """
        Setting up the rv_groups is a pain..
        :return:
        """
        # TODO Can this be done better?????
        # empty array for components where cloning
        # was performed - to get rid of the first
        # group
        cloned_comps = []
        registered_groups = []

        # dictionary for newly registered groups
        # this is necessary in case we do not
        # the newly registered groups have to
        # be assigned back to the spectra
        # otherwise we would not know which rv
        # belongs to which spectrum
        new_groups = dict()

        # get wavelength boundaries of defined regions
        wmins, wmaxs, regs = self.rl.get_wavelengths(verbose=True)

        # this dictionary is needed to have
        # unambiguous relationship between
        # rv_group, spectrum and region
        reg2rv = {x: [] for x in regs}

        # for every region we have a look if we have some datas
        for wmin, wmax, reg in zip(wmins, wmaxs, regs):

            # query spectra for each region
            observed_spectra = self.ol.get_spectra(wmin=wmin, wmax=wmax)

            for i, spectrum in enumerate(observed_spectra):

                # read out properties of spectra
                component = spectrum.component

                # there can be more spectral groups
                rv_groups = spectrum.group['rv']

                if not isinstance(rv_groups, (list, tuple)):
                    rv_groups = [rv_groups]

                for rv_group in rv_groups:
                    # readout groups that were already defined for all components
                    def_groups = self.sl.get_defined_groups(component='all', parameter='rv')['all']['rv']

                    # We define group for our observation
                    if rv_group is None:
                        gn = generate_least_number(def_groups)
                        reg2rv[reg].append(gn)

                        # save the newly registered group
                        if spectrum.filename not in list(new_groups.keys()):
                            new_groups[spectrum.filename] = []
                        new_groups[spectrum.filename].append(gn)

                    elif rv_group not in def_groups:
                        gn = rv_group
                        reg2rv[reg].append(rv_group)

                    # if the group is defined we only need to
                    # add it among the user defined one, so it
                    # so it is not deleted later
                    elif rv_group in def_groups:
                        registered_groups.append(rv_group)
                        reg2rv[reg].append(rv_group)
                        continue

                    # attachs new parameter to the StarList
                    # print component, gn
                    self.sl.clone_parameter(component, 'rv', group=gn)

                    if component not in cloned_comps:
                        if component == 'all':
                            cloned_comps.extend(self.sl.get_components())
                        else:
                            cloned_comps.append(component)
                        registered_groups.append(gn)

        # print registered_groups, cloned_comps
        # remove the default groups
        for c in cloned_comps:
            gref = self.sl.componentList[c]['rv'][0]['group']
            if gref not in registered_groups:
                self.remove_parameter(c, 'rv', gref)

        # back register the group numbers to the observed spectra
        for filename in list(new_groups.keys()):
            # print new_groups[filename]
            self.ol.set_spectrum(filename=filename, group={'rv': new_groups[filename]})

        # print self
        # finalize the list of rv_groups for each region
        self.rel_rvgroup_region = {x: np.unique(reg2rv[x]).tolist() for x in list(reg2rv.keys())}

    def _setup_all_groups(self):
        """
        Setting up all groups from observations is even a bigger pain.
        :return:
        """

        # get wavelength boundaries of defined regions
        wmins, wmaxs, regs = self.rl.get_wavelengths(verbose=True)

        # this dictionary is needed to have
        # unambiguous relationship between
        # rv_group, spectrum and region
        reg2rv = {x: [] for x in regs}

        # physical parameters
        phys_pars = self.sl.get_physical_parameters()
        phys_pars = [par for par in phys_pars if par not in ['lr']]

        # for every region we have a look if we have some datas
        for p_par in phys_pars:
            new_groups = dict()
            cloned_comps = []
            registered_groups = []

            for wmin, wmax, reg in zip(wmins, wmaxs, regs):

                # query spectra for each region
                observed_spectra = self.ol.get_spectra(wmin=wmin, wmax=wmax)

                # go over each observed spectrum
                for i, spectrum in enumerate(observed_spectra):

                    # read out properties of spectra
                    component = spectrum.component

                    # if the group is not defined for the s
                    if p_par in list(spectrum.group.keys()):

                        p_group = copy.deepcopy(spectrum.group[p_par])
                    else:
                        # self.ol.set_spectrum(spectrum.filename, group={p_par:0})
                        p_group = None

                    # readout groups that were already defined for all components
                    def_groups = self.sl.get_defined_groups(component='all', parameter=p_par)['all'][p_par]
                    # print p_par, def_groups

                    # We define group for our observation
                    if p_group is None:
                        if p_par == 'rv':
                            gn = generate_least_number(def_groups)
                            reg2rv[reg].append(gn)
                        # for other than rvs, the default group is 0
                        else:
                            # self.ol.set_spectrum(filename=spectrum.filename, group={p_par: 0})
                            # spectrum.group[p_par]=0
                            continue

                        # save the newly registered group
                        if spectrum.filename not in list(new_groups.keys()):
                            new_groups[spectrum.filename] = []
                        new_groups[spectrum.filename].append(gn)

                    elif p_group not in def_groups:
                        gn = p_group
                        reg2rv[reg].append(p_group)

                    # if the group is defined we only need to
                    # add it among the user defined one, so it
                    # so it is not deleted later
                    elif p_group in def_groups:
                        registered_groups.append(p_group)
                        reg2rv[reg].append(p_group)
                        continue

                    # attachs new parameter to the StarList
                    # print component, gn
                    self.sl.clone_parameter(component, p_par, group=gn)

                    if component not in cloned_comps:
                        if component == 'all':
                            cloned_comps.extend(self.sl.get_components())
                        else:
                            cloned_comps.append(component)
                        registered_groups.append(gn)

            # print registered_groups, cloned_comps
            # remove the default groups
            for c in cloned_comps:
                gref = self.sl.componentList[c][p_par][0]['group']
                if gref not in registered_groups:
                    self.remove_parameter(c, p_par, gref)

            # print new_groups
            # back register the group numbers to the observed spectra
            for filename in list(new_groups.keys()):
                # print p_par, new_groups
                self.ol.set_spectrum(filename=filename, group={'rv': new_groups[filename]})

            # finalize the list of rv_groups for each region
            self.rel_rvgroup_region = {x: np.unique(reg2rv[x]).tolist() for x in list(reg2rv.keys())}

    def update_fitter(self):
        """
        Pass the fitted parameters to the fitter.
        :return:
        """
        # get the fitted parameters
        fitpars = self.get_fitted_parameters()
        name = self.fitter.fittername
        kwargs = self.fitter.fit_kwargs

        # update the fitted parameters
        self.choose_fitter(name, fitparams=fitpars, **kwargs)

    def verify_spectra_and_regions(self):
        """
        Checks that all fitted spectra fit into at least one region.
        If not an error is raised
        :return:
        """

        # get all defined regions
        wmins, wmaxs = self.rl.get_wavelengths()

        # go over each spectrum
        for spectrum in self.ol.observedSpectraList['spectrum']:
            wave = spectrum.get_wavelength()
            owmin = wave.min()
            owmax = wave.max()

            # check whether the spectrum fits into at least one
            # region
            is_within = False
            for wmin, wmax in zip(wmins, wmaxs):
                if (wmin > owmin) & (wmax < owmax):
                    is_within = True
                    break
            if not is_within:
                warnings.warn('The spectrum:\n%s does not fit into any defined spectral region. These '
                              'spectra will be excluded from fitting.' % str(spectrum))


    @staticmethod
    def write_mc_result(f, treshold=100, outputname='fit.res'):
        """
        Writes the result of fitting
        :param f a fitting log
        :param outputname
        :param treshold
        :return:
        """

        # returns a dictionary of fitted parameters and their uncertainties
        pars = Interface.evaluate_mcmc(f, treshold=treshold)

        # creates the output string
        string = ''
        for c in list(pars.keys()):
            for p in list(pars[c].keys()):
                for row in pars[c][p]:
                    string += 'c:%15s p:%6s ' % (c, p)
                    string += 'g:%3i ' % (row['group'])
                    for key in ['best', 'gauss_mean', 'gauss_sigma', 'lower', 'upper']:
                        string += "%6s: %10.4f " % (key, row[key])
                    string += '\n'

        # writes it to a file
        ofile = open(outputname, 'w')
        ofile.writelines([string])
        ofile.close()

    def write_rvs(self, outputname=None):
        """
        Writes RVs defined to all groups --- usually there
        is only one spectrum per group.
        :param outputname: file where the output is written
        :return: rvs -- radial velocities per component and group,
                allgroup -- a list of all defined rv groups
                names --list of spectra names
        """

        # get define groups
        groups = self.get_defined_groups(component='all', parameter='rv')

        # get a parameter
        components = self.sl._registered_components

        # get a list of unique groups
        allgroups = []
        for c in components:
            allgroups.extend(groups[c]['rv'])
        allgroups =  np.unique(allgroups)

        # get all components for a given group
        rvs = {c: [] for c in components}
        names = []
        hjds = []
        groups = []

        for i, g in enumerate(allgroups):

            # get all observed spectra corresponding to the group
            obspecs = self.ol.get_spectra(rv=g)

            # get the radial velocities
            pars = self.sl.get_parameter(rv=g)

            for obspec in obspecs:
                for j, c in enumerate(components):

                    # append radial velocity
                    if c in list(pars.keys()):
                        rvs[c].append(pars[c][0]['value'])

                    # if an component is missing -9999.999 is assigned instead
                    else:
                        rvs[c].append(-9999.9999)

                # append name and hjd and group
                names.append(obspec.filename)
                hjds.append(obspec.hjd)
                groups.append(g)

        if outputname is not None:
            # opent the file
            ofile = open(outputname, 'w')

            # switch for writing hjds
            has_hjd = any([x is not None for x in hjds])

            # write the header
            if has_hjd:
                ofile.write("#%9s" % ('HJD')) # S
            else:
                ofile.write("#") # S
            for j in range(0, len(components)):
                headeritem = 'RV_' + components[j] # S
                ofile.write("%14s" % headeritem.upper()) # S
            ofile.write("%8s%15s" % ('GROUP', 'FILENAME')) # S
            ofile.write('\n')

            # write the rvs
            for i in range(0, len(names)):

                # what of HJD is not assigned
                if has_hjd:
                    ofile.write("%10s" % (str(hjds[i]))) # S
                else:
                    ofile.write("%10s" % ('')) # S
                for c in components:
                    ofile.write("%14.6f" % rvs[c][i]) # S
                ofile.write("%8s%15s" % (str(groups[i]).zfill(3), names[i])) # S
                ofile.write('\n')

        return rvs, allgroups, names

    def write_radiativeparameters(self, outputname=None): # S
        """
        Write raditive transfer parameters TEFF, VROT, LOGG_PRIM, LR and Z into a table
        """

        # get define groups
        groups = self.get_defined_groups(component='all', parameter='rv')

        # get a parameter
        components = self.sl._registered_components

        # get a list of unique groups
        allgroups = []
        for c in components:
            allgroups.extend(groups[c]['rv'])
        allgroups =  np.unique(allgroups)

        # Keys
        cpr = self.comparisonList[0]
        parlist = list(self.extract_parameters(cpr['parameters'][components[0]]).keys())

        # get all components for a given group
        rps = {p: {c: [] for c in components} for p in parlist} # radiative parameters
        names = []
        hjds = []
        groups = []

        gap = 3

        # get the first observed spectra corresponding to the group, since the radiative parameters are calculated for all input spectra and it does not matter which radiative parameters are requested
        obspecs = self.ol.get_spectra(rv=allgroups[0])

        pars = self.sl.get_parameter(rv=allgroups[0])
        cpr = self.comparisonList[0]

        # get the radiative transfer parameters
        for i, c in enumerate(components):
            for p in parlist:
                 if c in list(pars.keys()):
                       rps[p][c].append(self.extract_parameters(cpr['parameters'][c])[p])
                 else:
                       rps[p][c].append(-9999.9999)
                 # if an component is missing -9999.999 is assigned instead

        if outputname is not None:
            # opent the file
            ofile = open(outputname, 'w')

            # switch for writing hjds
            has_hjd = any([x is not None for x in hjds])

            # write the header
            first = True
            ofile.write('#')
            for p in parlist:
                for c in components:
                    if p != 'rv': # rvs are different for every spectrum and are printed into a table with write_rvs
                        if first:
                            gap = gap -1 # to compensate the # at the beginning of the header
                        parcomp = str(p) + '_' + str(c)
                        parcomp_len = len(parcomp)
                        parcomp_val_len = len(str(rps[p][c][0]))
                        if parcomp_val_len > parcomp_len:
                            str_len = "%"+ str(parcomp_val_len + gap)  +"s"
                        else:
                            str_len = "%"+ str(parcomp_len + gap)  +"s"
                        ofile.write(str_len % parcomp.upper()) # S
                        if first:
                            gap = gap +1
                            first = False
            ofile.write('\n')

            # write the radiative parameters
            for p in parlist:
                for c in components:
                      if p != 'rv':
                            parcomp_val = str(rps[p][c][0])
                            parcomp = str(p) + '_' + str(c)
                            parcomp_len = len(parcomp)
                            parcomp_val_len = len(str(rps[p][c][0]))
                            print((rps[p][c][0]))
                            if parcomp_val_len > parcomp_len:
                                str_len = "%"+ str(parcomp_val_len + gap)  +"s"
                            else:
                                str_len = "%"+ str(parcomp_len + gap)  +"s"
                            ofile.write(str_len % parcomp_val.upper()) # S
            ofile.write('\n')

        return rps, allgroups, names


#    def write_values(self, outputname=None):
#
#        # get define groups
#        groups = self.get_defined_groups(component='all', parameter='rv')
#
#        # get a parameter
#        components = self.sl._registered_components
#
#        # get a list of unique groups
#        allgroups = []
#        for c in components:
#            allgroups.extend(groups[c]['rv'])
#        allgroups =  np.unique(allgroups)
#
#        # Keys
#        cpr = self.comparisonList[0]
#        parlist = self.extract_parameters(cpr['parameters']['prim']).keys()
#
#        # get all components for a given group
#        values = {p: {c: [] for c in components} for p in parlist}
#        names = []
#        hjds = []
#        groups = []
#
#        for i, g in enumerate(allgroups):
#
#            # get all observed spectra corresponding to the group
#            obspecs = self.ol.get_spectra(rv=g)
#
#            # get the radial velocities
#            pars = self.sl.get_parameter(rv=g)
#            cpr = self.comparisonList[i]
#
#            for obspec in obspecs:
#                for j, c in enumerate(components):
#                    print(j,c)
#                    for p in parlist:
#                        if c in pars.keys():
#                            values[p][c].append(self.extract_parameters(cpr['parameters'][c])[p])
#                        else:
#                            values[p][c].append(-9999.9999)
#                    # if an component is missing -9999.999 is assigned instead
#                # append name and hjd and group
#                names.append(obspec.filename)
#                hjds.append(obspec.hjd)
#                groups.append(g)
#            print(values)
#
#        if outputname is not None:
#            # opent the file
#            ofile = open(outputname, 'w')
#
#            # switch for writing hjds
#            has_hjd = any([x is not None for x in hjds])
#
#            # write the header
#            if has_hjd: # S
#                ofile.write("#%9s" % ('HJD')) # S
#            else:
#                ofile.write("#") # S
#            for p in parlist:
#                for c in components:
#                    parcomp = str(p) + '_' + str(c)
#                    parcomp_len = len(parcomp)
#                    parcomp_val_len = len(str(values[p][c][0]))
#                    if parcomp_val_len > parcomp_len:
#                        str_len = "%"+ str(parcomp_val_len + 3)  +"s"
#                    else:
#                        str_len = "%"+ str(parcomp_len + 3)  +"s"
#                    if p == 'rv':
#                        str_len = "%14s"
#                    ofile.write(str_len % parcomp.upper()) # S
#            ofile.write("%8s%15s" % ('GROUP', 'FILENAME')) # S
#            ofile.write('\n')
#
#            for i in range(0, len(names)):
#
#                if has_hjd:
#                    ofile.write("%10s" % (str(hjds[i])))
#                #for c in components:
#                    #ofile.write("%15.6f" % rvs[c][i])
#                    for p in parlist:
#                        #for c in pars.keys():
#                        for c in components:
#                            parcomp_val = str(values[p][c][i])
#                            #parcomp_val_len = "%"+ str(len(str(values[p][c][0]))+6) +"s"
#                            parcomp = str(p) + '_' + str(c)
#                            parcomp_len = len(parcomp)
#                            parcomp_val_len = len(str(values[p][c][0]))
#                            if parcomp_val_len > parcomp_len:
#                                str_len = "%"+ str(parcomp_val_len + 3)  +"s"
#                            else:
#                                str_len = "%"+ str(parcomp_len + 3)  +"s"
#                            if p == 'rv':
#                                str_len = "%14s"
#                            ofile.write(str_len % parcomp_val.upper()) # S
#                # what of HJD is not assigned
#                ofile.write("%8s%15s" % (str(groups[i]).zfill(3), names[i]))
#                ofile.write('\n')
#
#        return values, allgroups, names

    def write_shifted_spectra(self, outputfile=None, residuals=False):
        """
        :return:
        """
        # setup name prefix
        if outputfile is None:
            outputfile = ''

        # go over each record within comparisonList
        for cp in self.comparisonList:

            if residuals:
                outputfile = cp['observed'].filename

            # extract description of the comparison
            wave = cp['wave']
            intens = sum_dict_keys(cp['synthetic'])
            wmin = cp['wmin']
            wmax = cp['wmax']
            component = cp['observed'].component
            korel = cp['observed'].korel
            rvgroup = cp['groups']['rv']

            # set name
            name = '_'.join([outputfile, 'c', component, 'wmin', str(wmin), 'wmax', str(wmax), 'g', str(rvgroup)]) \
                   + '.dat'

            # construct header of the file
            header = ''
            header += '# Component: %s\n' % str(component)
            header += '# Region: (%s,%s)\n' % (str(wmin), str(wmax))
            header += '# KOREL: %s\n' % str(korel)
            header += '# Residual: %s\n' % str(residuals)

            # write the synthetic spectrum
            ofile = open(name, 'w')
            ofile.writelines(header)
            if residuals:
                oi = cp['observed'].get_spectrum(wmin, wmax)[1]
                np.savetxt(ofile, np.column_stack([wave, oi - intens]), fmt='%15.8e')
            else:
                np.savetxt(ofile, np.column_stack([wave, intens]), fmt='%15.8e')
            ofile.close()

    def write_synthetic_spectra(self, component=None, region=None, rvgroups=None, outputname=None, korel=False):
        """
        Writes the synthetic spectra obtained through the fitting.
        :param component
        :param region
        :param outputname
        :param korel
        :return:
        """

        # set defaults for component
        if component is None:
            components = self.sl.get_components()
        if isinstance(component, str):
            components = [component]

        # set defaults for region
        if region is None:
            regions = self.rl.get_registered_regions()
        if isinstance(region, str):
            regions = [region]

        # go over each region
        for r in regions:

            # get the wavelengths
            wmin = self.rl.mainList[r]['wmin']
            wmax = self.rl.mainList[r]['wmax']

            # get defined groups for the region
            reg_groups = copy.deepcopy(self.rl.mainList[r]['groups'][0])
            phys_pars = [x for x in self.sl.get_physical_parameters() if x not in ['rv']]
            for par in phys_pars:
                if par not in list(reg_groups.keys()):
                    reg_groups[par] = 0

            # get regional parameters
            reg_pars = self.sl.get_parameter(**reg_groups)

            for c in components:
                # get defined rv groups
                if rvgroups is None:
                    rv_groups = self.sl.get_defined_groups(component=c, parameter='rv')[c]['rv']
                else:
                    if not isinstance(rv_groups, (list, tuple)):
                        rv_groups = [rv_groups]

                for rvg in rv_groups:

                    # the outputname
                    if outputname is not None:
                        oname = '_'.join([outputname, 'c', c, 'r', str(wmin),
                                          str(wmax), 'g', str(rvg)]) + '.dat'
                    else:
                        oname = '_'.join(['c', c, 'r', str(wmin),
                                          str(wmax), 'g', str(rvg)]) + '.dat'

                    if self.debug:
                        print("Writing spectrum: %s." % oname)

                    # get the parameters
                    # the radial velocity
                    rvpar = self.sl.get_parameter(rv=rvg)[c]

                    # remaining parameters
                    cpars = reg_pars[c]

                    # append the radial velocity
                    cpars.extend(rvpar)
                    # print cpars

                    # separate those that need to be computed,
                    # i.e. those not defined by the grid
                    computepars = [par for par in cpars if par['name'] in self._not_given_by_grid]
                    computepars = self.extract_parameters(computepars)
                    # print computepars

                    # compute the synthetic spectra
                    w, i = self.synthetics[r][c].get_spectrum(wmin=wmin, wmax=wmax, korel=korel, **computepars)

                    # constrauct header of the file
                    header = ''
                    header += '# Component: %s\n' % str(c)
                    header += '# Region: (%s,%s)\n' % (str(wmin), str(wmax))
                    header += '# KOREL: %s\n' % str(korel)
                    header += '# Parameters: %s\n' % str(self.extract_parameters(cpars))

                    # write the file
                    ofile = open(oname, 'w')
                    ofile.writelines(header)
                    np.savetxt(ofile, np.column_stack([w, i]), fmt='%15.10e')
                    ofile.close()

                # destroy the
                if rvgroups is None:
                    rv_groups = None


class List(object):
    """
    Future parent class for all the lists, which are dictionaries... :-)
    """
    def __init__(self, l=None, debug=False):
        """
        :param l: the list stored within the class
        :param debug: debugmode on/off
        :return:
        """
        # list
        if l is not None:
            self.mainList = l
        else:
            self.mainList = {}

            # setup debug mode
            self.debug = debug

    def clear_all(self):
        """
        Clears the list
        :return: None
        """

        self.mainList = {}


class ObservedList(object):
    """
    A helper class which groups all observed spectra and
    prepares necessary parameters for fitting.
    """
    def __init__(self, observedSpectraList=None, debug=False):
        """
        :param observedSpectraList: this should not be used in general, this creates the class
                    assuming that we are passin the self.observedSpectraList,
                    this shoudl not be used probably
        :param debug: debug mode
        :return:
        """

        # dictionary containing all observed spectra, apart from that
        # it also carries information on. A group fro radial velocities
        # has to be always set, because we intend to fit spectra acquired
        # on different times.
        self.observedSpectraList = dict(spectrum=[], group=dict(), properties=dict())
        self.groupValues = dict()

        # list of properties
        self._property_list = ['component', 'filename', 'hasErrors', 'korel', 'loaded', 'wmin', 'wmax']
        # self._queriables = copy.deepcopy(self._property_list).extend(['group'])

        # although wmin, wmax can be queried, it is treated separately from the remaining
        # parameters, because it cannot be tested on equality
        self._queriables = [x for x in self._property_list if x not in ['wmin', 'wmax']]
        self._queriable_floats = ['wmin', 'wmax']

        # initialize with empty lists
        self.observedSpectraList['properties'] = {key: [] for key in self._property_list}

        # debug
        self.debug = debug

        if observedSpectraList is not None:
            self.observedSpectraList = observedSpectraList
            self.read_groups()
            self.read_properties()
            self.groupValues = self.get_defined_groups()

    def __len__(self):
        """
        Returns number of attached observed spectra.
        """
        return len(self.observedSpectraList['spectrum'])

    def __str__(self):
        """
        String method for the class
        :return:
         string.. string representation of teh class
        """
        string = 'List of all attached spectra:\n'
        for i, spectrum in enumerate(self.observedSpectraList['spectrum']):
            string += str(spectrum)
        return string

    def add_one_observation(self, obs=None, update=True, **kwargs):
        """
        Adds observation to the list.
        :param obs observed spectrum wrapped in ObservedSpectrum class
        :param update - update the observed spectra list
        :param kwargs
            see class ObservedSpectrum (observations module) for details.
        """
        # adds the spectrum and loads it
        if self.debug:
            kwargs['debug'] = True
        if obs is None:
            obs = ObservedSpectrum(**kwargs)

        self.observedSpectraList['spectrum'].append(obs)

        if self.debug:
            print("Adding spectrum: %s" % (str(obs)))

        # builds the observedSpectraList dictionary
        if update:
            self.read_groups()
            self.read_properties()
            self.groupValues = self.get_defined_groups()

    def add_observations(self, spec_list, update=True):
        """
        :param spec_list: list of dictionaries - key words are
                the same as for ObservedSpectrum class constructor
        :param update: whether to update the dictionary
                with the properties of the observed spectra
        """
        # attachs the spectra
        for rec in spec_list:
            if isinstance(rec, dict):
                self.add_one_observation(update=False, **rec)
            else:
                self.add_one_observation(update=False, obs=rec)

        # builds the observedSpectraList dictionary
        if update:
            self.read_groups()
            self.read_properties()
            self.groupValues = self.get_defined_groups()

    def clear_all(self):
        """
        Clears all spectra.
        """
        self.__init__()

    def get_data_groups(self, components):
        """
        Returns a dictionary, containing a record
        on defined group for each component.
        :param components: a list of queried components
        :return:
        """
        groups = dict()
        for component in components:
            osl = self.get_spectra(verbose=True, component=component)

            if self.debug:
                print('Queried observed spectra: %s for component: %s.' % (str(osl), component))

            if len(osl) > 0:
                groups[component] = ObservedList(observedSpectraList=osl).get_defined_groups()

        return groups

    def get_defined_groups(self, component=None):
        """
        Reads all groups and values that are set
        for the spectra in the list.
        :param component
        :return dictionary of defined group for all/given component
        """
        if component == 'all':
            component = None

        # empty dicitonary for the values
        groups = dict()

        # go through ech spectrum and store defined values
        for spectrum in self.observedSpectraList['spectrum']:

            # select component
            if component is not None and spectrum.component != component:
                continue

            for key in list(spectrum.group.keys()):
                if key not in list(groups.keys()):
                    groups[key] = []
                if isinstance(spectrum.group[key], (list, tuple)):
                    groups[key].extend(spectrum.group[key])
                else:
                    groups[key].append(spectrum.group[key])

        # only unique values are needed
        for key in list(groups.keys()):
            groups[key] = np.unique(groups[key]).tolist()

        return groups

    def get_resolution(self, verbose=False):
        """
        Reads resoolution for each spectrum
        :param verbose
        :return:
        """
        # create a list of resolutions
        resolutions = np.zeros(len(self))
        for i in range(0, len(self)):
            resolutions[i] = self.observedSpectraList['spectrum'][i].step

        # if verbose is set returns resolution for each spectrum
        if verbose:
            return resolutions

        # or just the maximum value
        else:
            return np.max(resolutions)

    def get_spectra(self, verbose=False, permissive=False,  **kwargs):
        """
        :param kwargs.. properties of ObservedSpectrum,
          that we want to return. This function does not
          search the individual spectra, but the dictionary
          observedSpectraList.
        :param verbose return the whole bserved spectra list
          stub
        :param permissive

          In general this could be - wmin, wmax, group,
          component etc..
        :return:
          speclist = all spectra that have the queried properties
        """

        # First of all check that all passed arguments are
        # either defined among queriables or is in groups
        to_pass = []
        for key in list(kwargs.keys()):
            # print key, self._queriables
            if (key not in self._queriables) & (key not in self._queriable_floats):
                if key not in list(self.groupValues.keys()):
                    if permissive:
                        to_pass.append(key)
                        continue
                    raise KeyError('Keyword %s is not defined. This either means, that it was not set up for '
                                   'the observed spectra, or is an attribute of Observed spectrum, but is not '
                                   'defined among queriables, or is wrong.' % key)

        # create a copy of the spectralist
        osl = copy.deepcopy(self.observedSpectraList)

        # debug string
        dbg_string = 'Queried: '

        # reduce the list
        for key in list(kwargs.keys()):
            #
            if key in to_pass:
                continue

            # find all matching for a given key-word
            keytest = key.lower()

            # these can be tested on equality as strings
            if keytest in self._queriables:
                vind = np.where(np.array(osl['properties'][keytest], dtype=str) == str(kwargs[key]))
            elif keytest == 'component':
                vind = np.where((np.array(osl['properties'][keytest], dtype=str) == str(kwargs[key])) or
                                (np.array(osl['properties'][keytest], dtype=str) == 'all'))[0]
            # that cannot be tested on equality
            elif keytest == 'wmin':
                vind = np.where(np.array(osl['properties'][keytest]) <= kwargs[key])[0]
            elif keytest == 'wmax':
                vind = np.where(np.array(osl['properties'][keytest]) >= kwargs[key])[0]

            # those that are defined in groups
            elif keytest in list(osl['group'].keys()):
                vind = []
                for i in range(0, len(osl['spectrum'])):
                    if isinstance(osl['group'][keytest][i], (tuple, list)):
                        if kwargs[key] in osl['group'][keytest][i]:
                            vind.append(i)
                    else:
                        if kwargs[key] == osl['group'][keytest][i]:
                            vind.append(i)
                vind = np.array(vind)

            if len(vind) == 0:
                warnings.warn('No spectrum matching %s: %s was found in the '
                              'list of observed spectra:\n%sDo not panic, it can '
                              'still be listed among \'all\'.' % (key, str(kwargs[key]), str(self)))
                return []

            if self.debug:
                dbg_string += '%s: %s ' % (key, str(kwargs[key]))
                print("%s.. %s spectra remain." % (dbg_string, str(len(vind))))

            # extract them from the list
            for dic in list(osl.keys()):
                # if the key refers to a dictionary
                if isinstance(osl[dic], dict):
                    for sub_key in list(osl[dic].keys()):
                        osl[dic][sub_key] = (np.array(osl[dic][sub_key])[vind]).tolist()

                # if it refers to a list or array
                else:
                    osl[dic] = (np.array(osl[dic])[vind]).tolist()

        # simple output, just spectra
        if not verbose:
            return osl['spectrum']
        # otherwise the whole remnant of the
        # observed spectra list is returned
        else:
            return osl

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
            if l.find('OBSERVEDLIST') > -1:
                data_start = i
                break

        # check that there are actually some data in the file
        # the algorithm failed to load the class
        if data_start >= len(lines):
            return False

        # create a regionlist
        ol = ObservedList()

        # from here the file is actually being read
        for i, l in enumerate(lines[data_start+1:]):

            # once we reach regionlist, we end
            if l.find('OBSERVEDLIST') > -1:
                break
            # split the linbe
            d = l.split()
            # print d
            if d[0].find('filename') > -1:
                i = 0
                cdict = {}
                # print d
                while i < len(d):
                    if d[i].find(':') > -1:
                        j = i + 1
                        while j < len(d) and d[j].find(':') == -1:
                            j += 1
                        stub = d[i:j]
                        if len(stub) < 3:
                            cdict[d[i].strip(':')] = stub[1].strip(':[]{}\'\"')
                        else:
                            cdict[d[i].strip(':')] = list(map(int, [stub[k].strip(':[]{}\'\"') for k in range(1, len(stub))]))
                        i = j

                # it is a mess with the global error :-(
                cdict['error'] = cdict['global_error']
                del cdict['global_error']

                # cast the parameters to the correct types
                parnames = ['filename', 'component', 'error', 'korel', 'hjd']
                cast_types = [str, str, float, string2bool, float]
                for k in list(cdict.keys()):
                    if k in parnames:
                        i = parnames.index(k)
                        if cdict[k] != 'None':
                            cdict[k] = cast_types[i](cdict[k])
                        else:
                            cdict[k] = None
                    else:
                        # the remaining must be groups
                        cdict[k] = int(cdict[k])

                # add the parameter if it does not exist
                groups = {key: cdict[key] for key in list(cdict.keys()) if key not in parnames}
                kwargs = {key: cdict[key] for key in list(cdict.keys()) if key in parnames}
                ol.add_one_observation(group=groups, **kwargs)

            # do the same for enviromental keys
            if d[0].find('env_keys') > -1:
                # the first string is just identification
                d = d[1:]

                # secure corrct types
                recs = ['debug']
                cast_types = [string2bool]
                cdict = {d[i].rstrip(':'): d[i+1] for i in range(0, len(d), 2)}
                for k in list(cdict.keys()):
                    if k in recs:
                        i = recs.index(k)
                        ctype = cast_types[i]
                        cdict[k] = ctype(cdict[k])

                    # assign the vlues
                    setattr(ol, k, cdict[k])
        # finally assign everything to self
        attrs = ['debug', 'groupValues', 'observedSpectraList']
        for attr in attrs:
            setattr(self, attr, getattr(ol, attr))

        # if we got here, we loaded the data
        return True

    def read_groups(self):
        """
        Updates the dictionary observedSpectraList with group
        records for every single observations and creates
        the dictionary groupValues which contains lists of
        all defined groups for every parameter.

        For parameters != 'rv':
            If at least one spectrum has a group assigned
            it is automatically assumed, that it does not
            belong among the remaining ones. This means
            that all remaining spectra are assigned their
            own group.

        For parameters == 'rv':
            Each spectrum is assigned unique RV group,
            unless this is overriden by the user by setting
            them up. This comes natural, since we are
            likely to fit spectra from different times,
            regions, where slight shifts in rv are
            very likely.
        """

        # First go through each spectrum to see, which
        # groups were defined by user
        groups = self.get_defined_groups()
        # print groups

        # check that rv has been setup - mandatory, because each observed spectrum
        # is assigned its own rv_group
        if 'rv' not in list(groups.keys()):
            groups['rv'] = []

        # assign empty group arrays
        for key in list(groups.keys()):
            self.observedSpectraList['group'][key] = np.zeros(len(self)).astype('int16').tolist()

        # Assigning groups to every spectrum
        for i, spectrum in enumerate(self.observedSpectraList['spectrum']):
            for key in list(groups.keys()):
                # If not user defined the maximal possible
                # group is assigned
                if key != 'rv':
                    gn = spectrum.get_group(key)
                    def_groups = groups[key]
                    # print key, gn, def_groups

                    # if spectrum has no group, but some groups have been defined,
                    # the group is assigned to the least number not in defuined groups
                    if gn is None and len(def_groups) > 0:
                        gn = 0
                        while gn in def_groups:
                            gn += 1

                    # if no group is defined for all spectra, start with zero
                    elif gn is None and len(def_groups) == 0:
                        gn = 0

                    # store the groupnumber
                    self.observedSpectraList['group'][key][i] = gn

                else:
                    gn = spectrum.get_group(key)
                    if gn is None:
                        self.observedSpectraList['group'][key][i] = None
                    else:
                        self.observedSpectraList['group'][key][i] = gn

        # propagate the groups back to spectra
        self._set_groups_to_spectra()

    def read_properties(self):
        """
        Goes through the attached spectra and reads
        stores them within the observedSpectraList
        dictionary.
        """
        # initialize with empty lists
        for key in self._property_list:
            self.observedSpectraList['properties'][key] = np.empty(len(self), dtype=object)

        # fill the dictionary
        for i, spectrum in enumerate(self.observedSpectraList['spectrum']):
            for key in self._property_list:
                self.observedSpectraList['properties'][key][i] = getattr(spectrum, key)

    def save(self, ofile):
        """
        Saves the class. It should be retrievable from the file.
        :param ofile:
        :return:
        """
        # Open the file
        if isinstance(ofile, str):
            ofile = open(ofile, 'w+')

        # parameters listed for each record in the RegionList
        enviromental_keys = ['debug']
        string = ' OBSERVEDLIST '.rjust(105, '#').ljust(200, '#') + '\n'
        for s in self.observedSpectraList['spectrum']:
            keys = ['filename', 'component', 'korel', 'global_error', 'groups', 'hjd']
            for k in keys:
                if k not in ['groups']:
                    string += '%s: %s ' % (k, str(getattr(s, k)))
                else:
                    for gk in list(s.group.keys()):
                        if isinstance(s.group[gk], (list, tuple)):
                            string += '%s: ' % gk
                            for gn in s.group[gk]:
                                string += '%s ' % str(gn)
                        else:
                            string += '%s: %s ' % (gk, str(s.group[gk]))
            string += '\n'
        # attach enviromental keys
        for ekey in enviromental_keys:
            string += "%s: %s " % (ekey, str(getattr(self, ekey)))
        string += '\n'
        # finalize the string
        string += ' OBSERVEDLIST '.rjust(105, '#').ljust(200, '#') + '\n'

        # write the result
        ofile.writelines(string)

    def set_spectrum(self, filename=None, **kwargs):
        """
        Sets spectrum to a given value.
        :param filename
        :param kwargs:
        :return:
        """
        # print kwargs
        for i in range(0, len(self)):
            if self.observedSpectraList['spectrum'][i].filename == filename:
                for key in list(kwargs.keys()):
                    setattr(self.observedSpectraList['spectrum'][i], key, kwargs[key])
                if key == 'group':
                    self.observedSpectraList['spectrum'][i].set_group(kwargs[key])
                # print self

        self.read_groups()
        self.groupValues = self.get_defined_groups()

    def _set_groups_to_spectra(self):
        """
        Propagates groups, which are set in observedSpectraList,
        in individual spectra.
        """
        for i in range(0, len(self.observedSpectraList['spectrum'])):
            group = {key: self.observedSpectraList['group'][key][i] for key in list(self.observedSpectraList['group'].keys())}
            self.observedSpectraList['spectrum'][i].set_group(group)


class RegionList(List):
    """
    """
    def __init__(self, **kwargs):
        """
        Class constructor
        :return:None
        """

        # setup the parent class
        super(RegionList, self).__init__(**kwargs)

        # registered keywords
        self._registered_records = ['components', 'groups', 'wmin', 'wmax']

        # if not given along the class a blank one is created
        if len(list(self.mainList.keys())) < 1:
            self.mainList = {}
            self._registered_regions = []
            self._user_defined_groups = {}
        else:
            self._registered_regions = self.get_registered_regions()

    def __str__(self):
        """
        String representation of the class.
        :return: string
        """

        string = ''

        # go over regions
        for key0 in list(self.mainList.keys()):
            # region properties
            string += "Region name: %s: (wmin, wmax) = (%s, %s):\n" % (key0, str(self.mainList[key0]['wmin']),
                                                                       str(self.mainList[key0]['wmax']))
            # componentn properties
            for i in range(0, len(self.mainList[key0]['components'])):
                string += "%s: %s " % ('component', str(self.mainList[key0]['components'][i]))
                string += "%s: %s " % ('groups', str(self.mainList[key0]['groups'][i]))
                string += '\n'
        return string

    def add_region(self, component='all', identification=None, wmin=None, wmax=None, groups=None):
        """
        :param component: component for whichg the region apply
        :param identification
        :param wmin: minimal wavelength
        :param wmax: maximal wavelength
        :param groups: group numbers for this region
        :return: None
        """

        # if we are crazy and want to set this up
        # either by wavelength or by identification
        if (wmin is None or wmax is None) and identification is None:
            raise ValueError('Boundaries are not set properly: (wmin,wmax)= (%s, %s)' % (str(wmin), str(wmax)))
        else:
            if (wmin >= wmax) and identification not in self._registered_regions:
                raise ValueError('wmin is greater than wmax: %s > %s '
                                 'or the region: %s is not registered.' % (str(wmin), str(wmax), identification))

        # convert component/group/identification keys to lowercase
        if groups is not None:
            groups = keys_to_lowercase(groups)
        else:
            groups = {}

        # make component case insensitive
        component = component.lower()
        ident = identification
        if ident is not None:
            ident = ident.lower()

        # maybe the region has been already defined
        if ident in list(self.mainList.keys()):
            region = ident
        elif ident is None:
            region = self.get_region(wmin, wmax)
        else:
            region = None

        # if there is a region exists and the component is all,
        # there is no point to attach it
        # print region, component
        if (region is not None) and (component == 'all'):
            warnings.warn('The region already exists as region: %s -> doing nothing.' % region)
            return

        # if it is not empty
        if region is not None:

            if self.debug:
                print("Adding component: %s to region: %s" % (component, region))

            # check that the component ws not set earlier
            if self.has_component(region, component):
                warnings.warn('The component: %s is already set for region: %s. -> doing nothing.'
                            % (component, region))
                return

            # get lr from the region first record
            # print groups, self.mainList[region]['groups']
            groups['lr'] = self.mainList[region]['groups'][0]['lr']

            self.read_user_defined_groups(groups)

            # store everything apart from the wmin, wmax
            self.mainList[region]['groups'].append(groups)
            self.mainList[region]['components'].append(component)

            # readout user-defined groups
            self.read_user_defined_groups(groups)
        else:

            # setup identification for
            if ident is None:
                ident = 'region' + str(len(self._registered_regions)).zfill(2)

            if self.debug:
                print("Creating new region: %s." % ident)

            # register the new region
            self.mainList[ident] = dict(wmin=wmin, wmax=wmax, components=[component], groups=[])
            self._registered_regions.append(ident)

            # if the luminosity group is not defined
            if 'lr' not in list(groups.keys()):
                all_groups = self.get_defined_groups()
                if 'lr' in list(all_groups.keys()):
                    def_groups = all_groups['lr']
                else:
                    def_groups = []
                gn = 0
                while gn in def_groups:
                    gn += 1
                groups['lr'] = gn

            # add groups to the list
            self.mainList[ident]['groups'].append(groups)
            # readout user-defined groups
            self.read_user_defined_groups(groups)

        self.setup_undefined_groups()

    def clear_all(self):
        """
        Clears the class.
        :return:
        """

        super(RegionList, self).clear_all()
        self._registered_regions = []
        self._user_defined_groups = {}

    def get_defined_groups(self):
        """
        Returns plain list of all defined groups regardless of their components.
        :return: list of defined groups
        """
        groups = {}
        for reg in self._registered_regions:
            for rec in self.mainList[reg]['groups']:
                for key in list(rec.keys()):
                    if key not in list(groups.keys()):
                        groups[key] = [rec[key]]
                    else:
                        if rec[key] not in groups[key]:
                            groups[key].append(rec[key])

        return groups

    def get_region(self, wmin, wmax):
        """
        Checks that a region with this wavelength range
        does not exist.
        :param wmin
        :param wmax
        :return:
        """

        for region in self.mainList:
            if (abs(self.mainList[region]['wmin'] - wmin) < ZERO_TOLERANCE) & \
               (abs(self.mainList[region]['wmax'] - wmax) < ZERO_TOLERANCE):
                return region
        return None

    def get_region_groups(self):
        """
        A dictionary of groups defined for regions component by component.
        :return: dictionary containing records on groups
                which can be directly passed to type StarList
                through set_groups
        """
        groups = {}

        # go over each region
        for reg in list(self.mainList.keys()):
            for i in range(0, len(self.mainList[reg]['components'])):
                component = self.mainList[reg]['components'][i]
                comp_groups = self.mainList[reg]['groups'][i]

                # setup component
                if component not in list(groups.keys()):
                    groups[component] = {}

                # setup keys
                for key in list(comp_groups.keys()):
                    if key not in list(groups[component].keys()):
                        groups[component][key] = [comp_groups[key]]
                    else:
                        if comp_groups[key] not in groups[component][key]:
                            groups[component][key].append(comp_groups[key])
        return groups

    def get_registered_regions(self):
        """
        Returns an array of registered regions.
        :return:
        """
        return list(self.mainList.keys())

    def get_wavelengths(self, verbose=False):
        """
        Returns registered wavelengths
        :param verbose
        :return: wmins, wmaxs = arrays of minimal/maximal wavelength for each region
        """
        wmins = []
        wmaxs = []
        regs = []
        for reg in list(self.mainList.keys()):
            wmins.append(self.mainList[reg]['wmin'])
            wmaxs.append(self.mainList[reg]['wmax'])
            regs.append(reg)

        if verbose:
            return wmins, wmaxs, regs
        else:
            return wmins, wmaxs

    def get_regions_from_obs(self, ol, append=False):
        """
        Reads the region from a list of observations. In general this
        function should not be used for fitting, because it
        makes no sense to fit the whole spectrum.

        :param ol: list of ObservedSpectrum
        :param append are we appending to existing list?
        :return: list of unique limits
        """
        if len(ol) == 0:
            raise ValueError('Cannot setup regions from observed spectra, because'
                             ' their list is empty!')

        # clear the regions if needed
        if not append:
            self.clear_all()

        # empty arrays for limits
        limits = {}
        # the rounding is there get over stupid problems with float precision
        for obs in ol:
            component = obs.component
            if component not in limits:
                limits[component] = [[], []]

            limits[component][0].append(np.ceil(obs.wmin))
            limits[component][1].append(np.floor(obs.wmax))

            # get only unique values
            for i in range(0, 2):
                limits[component][i] = np.unique(limits[component][i])

        # check that something funny did not happen
        for component in list(limits.keys()):
            if len(limits[component][0]) != len(limits[component][1]):
                raise ValueError('The limits were not read out correctly from observed spectra.')

            # setup the regions
            for i in range(0, len(limits[component][0])):
                self.add_region(component=component,
                                wmin=limits[component][0][i],
                                wmax=limits[component][1][i])

        return limits

    def has_component(self, region, component):
        """
        Checks that certain component was attached for a given
        region.
        :param region:
        :param component:
        :return: bool has/has_not the component
        """

        for regcomp in self.mainList[region]['components']:
            if (regcomp == component) or (regcomp == 'all'):
                return True
        return False

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
            if l.find('REGIONLIST') > -1:
                data_start = i
                break

        # check that there are actually some data in the file
        # if not we failed
        if data_start >= len(lines):
            return False

        # create a regionlist
        rl = RegionList()

        # from here the file is actually being read
        for i, l in enumerate(lines[data_start+1:]):

            # once we reach regionlist, we end
            if l.find('REGIONLIST') > -1:
                break
            # split the linbe
            d = l.split()
            # print d
            if d[0].find('identification') > -1:
                cdict = {d[i].rstrip(':'): d[i+1] for i in range(0, len(d), 2)}
                # print cdict
                # cast the paramneters to teh correct types
                parnames = ['wmin', 'wmax', 'identification', 'component']
                cast_types = [float, float, str, str]
                for k in list(cdict.keys()):
                    if k in parnames:
                        i = parnames.index(k)
                        cdict[k] = cast_types[i](cdict[k])
                    else:
                        # the remaining must be groups
                        cdict[k] = int(cdict[k])

                # add the parameter if it does not exist
                groups = {key: cdict[key] for key in list(cdict.keys()) if key not in parnames}
                kwargs = {key: cdict[key] for key in list(cdict.keys()) if key in parnames}
                # print groups
                # # print kwargs
                rl.add_region(groups=groups, **kwargs)

            # do the same for enviromental keys
            if d[0].find('env_keys') > -1:
                # the first string is just identification
                d = d[1:]

                # secure corrct types
                recs = ['debug']
                cast_types = [string2bool]
                cdict = {d[i].rstrip(':'): d[i+1] for i in range(0, len(d), 2)}
                for k in list(cdict.keys()):
                    if k in recs:
                        i = recs.index(k)
                        ctype = cast_types[i]
                        cdict[k] = ctype(cdict[k])

                    # assign the vlues
                    setattr(rl, k, cdict[k])
        # finally assign everything to self
        attrs = ['_registered_records', '_registered_regions', '_user_defined_groups',
                 'mainList', 'debug']
        for attr in attrs:
            setattr(self, attr, getattr(rl, attr))

        # if we got here, we loaded the data
        return True

    def read_user_defined_groups(self, groups):
        """
        When adding new region, all user defined groups
        are read out to properly set the default groups
        :param groups groups to be read
        :return: None
        """
        for key in list(groups.keys()):
            if key not in list(self._user_defined_groups.keys()):
                self._user_defined_groups[key] = [groups[key]]
            else:
                if groups[key] not in self._user_defined_groups[key]:
                    self._user_defined_groups[key].append(groups[key])

    def save(self, ofile):
        """
        Saves the class. It should be retrievable from the file.
        :param ofile:
        :return:
        """
        # Open the file
        if isinstance(ofile, str):
            ofile = open(ofile, 'w+')

        # parameters listed for each record in the RegionList
        enviromental_keys = ['debug']
        string = ' REGIONLIST '.rjust(105, '#').ljust(200, '#') + '\n'
        for ident in list(self.mainList.keys()):
            for i, c in enumerate(self.mainList[ident]['components']):
                string += 'identification: %s ' % ident

                # write the wavelengths
                for lkey in ['wmin', 'wmax']:
                    string += '%s: %s ' % (lkey, str(self.mainList[ident][lkey]))

                # write components
                string += "component: %s " % c

                # and groups
                for gkey in list(self.mainList[ident]['groups'][i].keys()):
                    string += "%s: %s " % (gkey, str(self.mainList[ident]['groups'][i][gkey]))
            string += '\n'

        # setup additional parameters
        string += 'env_keys: '
        for ekey in enviromental_keys:
            string += '%s: %s ' % (ekey, str(getattr(self, ekey)))
        string += '\n'
        string += ' REGIONLIST '.rjust(105, '#').ljust(200, '#') + '\n'
        # write the remaining parameters
        ofile.writelines(string)

    def setup_undefined_groups(self):
        """
        User can be a bit lazy. If we split some parameter
        into more groups, we can only set group for few
        and the remaining dataset gets a default one.

        This nonetheless has to be run after all
        regions were attached. If we do this
        earlier, we will get into serious problems.
        :return:
        """
        # defined groups
        groups = self.get_defined_groups()

        # setup default group numbers for region->component
        # with unset group
        for region in self._registered_regions:
            for i, comp_group in enumerate(self.mainList[region]['groups']):

                # go over each defined group
                for key in list(groups.keys()):
                    # if the key is unset for the component
                    # we have to assign some. This must
                    # not be one of the user-defined.
                    # That is why we maintain dictionary
                    # of user defined groups.
                    if key not in list(comp_group.keys()):
                        gn = 0
                        while gn in self._user_defined_groups[key]:
                            gn += 1
                        self.mainList[region]['groups'][i][key] = gn


class StarList(object):
    """
    """
    def __init__(self, debug=False):
        """
        """

        # set up debug mode
        self.debug = debug

        # define empty list of components
        self.componentList = {}

        # array storing registered components
        self._registered_components = []

        # defined groups
        self.groups = {}

        # empty dictionary for the list of
        # fitted types
        self.fitted_types = {}

    def __len__(self):
        """
        Returns number of parameters.
        :return: l
        """
        pass

    def __str__(self):
        """
        :return: string = string represantation of the class
        """
        string = ''
        for component in list(self.componentList.keys()):
            string += "Component: %s\n" % component
            for parkey in list(self.componentList[component].keys()):
                for par in self.componentList[component][parkey]:
                    string += str(par)

        return string

    def add_component(self, component=None, groups={}, use_defaults=True, **kwargs):
        """
        Setups a component - if no kwargs are given,
        all parameters from the parameter_definitions
        are taken.

        If one wants to not-include a parameter,
        params = None, has to be passed. If one
        wants to add a parameter, that is not
        defined in parameter definitions, just
        pass parameter + value.

        :param component: Registration string of the component
                if None is given, it is registred as 'componentXX'
        :param groups: group set to all parameters of a component
        :param use_defaults
        :param kwargs:
        :return:
        """

        # setup name of the component and create a record within
        # component list
        if component is None:
            component = 'component' + str(len(self._registered_components))

        # register he component
        self._registered_components.append(component)

        # the parameters will be stored in a dictionary
        self.componentList[component] = dict()
        pd = copy.deepcopy(parameter_definitions)

        # setup groups for default parameters
        for key in list(groups.keys()):
            if key in list(pd.keys()):
                pd[key]['group'] = groups[key]

        # process the keyword-arguments
        for key in list(kwargs.keys()):
            keytest = key.lower()
            # if we pass par + value, it is just stored
            if keytest in list(pd.keys()) and kwargs[key] is not None:
                self.componentList[component][keytest] = []
                self.componentList[component][keytest].append(Parameter(**pd[key]))
                self.componentList[component][keytest][-1]['value'] = kwargs[key]
            elif kwargs[key] is None:
                warnings.warn('The parameter %s is set to %s. Therefore it is not '
                              'included into component parameters.' % (key, str(kwargs[key])))
            elif keytest not in list(pd.keys()) and kwargs[key] is not None:

                # set up group
                if keytest in list(groups.keys()):
                    group = groups[keytest]
                self.componentList[component][keytest] = []
                self.componentList[component][keytest].append(Parameter(name=key, value=kwargs[key], group=group))
                self.componentList[component][keytest][-1].set_empty()
                warnings.warn('The parameter %s: %s is not set among the '
                              'parameter definitions. Therefore you should pay '
                              'attention to ist settings.')

        # pass all unset parameters in definitions
        if use_defaults:
            for key in list(pd.keys()):
                if key not in list(self.componentList[component].keys()):
                    self.componentList[component][key] = []
                    self.componentList[component][key].append(Parameter(**pd[key]))

        # readout the groups
        self.read_groups()
        self.get_fitted_types()

    def add_parameter_to_component(self, component, p=None, **kwargs):
        """
        Adds a parameter to a specific component.
        :param component: component for which we want to add a parameter
        :param p: assigning directly the Parameter type
        :param kwargs: see Parameter class for description
        :return:
        """
        if p is None:
            self.componentList[component][kwargs['name']] = []
            self.componentList[component][kwargs['name']].append(Parameter(**kwargs))
        else:
            # print p['name']
            self.componentList[component][p['name']].append(copy.deepcopy(p))

        # redefine groups
        self.read_groups()
        self.get_fitted_types()

    def add_parameter_to_all(self, **kwargs):
        """
        Adds a parameter to all components
        :param kwargs: see Parameter class
        :return: None
        """
        for component in self._registered_components:
            self.add_parameter_to_component(component, **kwargs)

    def clear(self):
        """
        Clears the component list
        :return: None
        """
        self.componentList = {}
        self._registered_components = []

    def clone_parameter(self, component, parameter, index=0, **kwargs):
        """
        Clones a parameter and stores it for a given component.
        This function will be primarily used to clone parameters
        to acount for different groups.

        :param component: component for which we want to clone the parameter
        :param parameter: the cloned parameter
        :param index : the specific cloned parameter
        :param kwargs: values we want to change for the parameter
        :return: clone type_Parameter - the cloned parameter
        """
        # in case we pass
        if component.lower() == 'all':
            components = self._registered_components
        else:
            components = [component]

        clones = []
        # go over each component
        for component in components:

            # copy the parameter
            clone = copy.deepcopy(self.componentList[component][parameter][index])
            clones.append(clone)

            # adjust its values
            for key in list(kwargs.keys()):
                keytest = key.lower()
                clone[keytest] = kwargs[key]

            # append the new component to the componentlist
            self.add_parameter_to_component(component, p=clone)

        return clones

    def copy(self):
        """
        Creates a deepcopy of the class StarList.
        :return:
        """
        other = StarList()
        for attr in ['_registered_components', 'componentList', 'debug',
                     'fitted_types', 'groups']:
            v = getattr(self, attr)
            setattr(other, attr, copy.deepcopy(v))

        return other

    def delete_hollow_groups(self):
        """
        Goes through parameters and deletes those that
        are set to None.
        :return: None
        """

        for component in self._registered_components:
            for parkey in list(self.componentList[component].keys()):
                i = 0
                while i < len(self.componentList[component][parkey]):

                    # if the parameter group is not, it is deleted
                    if self.componentList[component][parkey][i]['group'] is None:
                        del self.componentList[component][parkey][i]
                    else:
                        i += 1

    def delete_duplicities(self):
        """
        Delete duplicities in groups.
        :return: None
        """
        for component in self._registered_components:
            # groups can a have to be the same for two components ofc,
            def_groups = []
            for parkey in list(self.componentList[component].keys()):
                i = 0
                while i < len(self.componentList[component][parkey]):
                    if self.componentList[component][parkey][i]['group'] not in def_groups:
                        def_groups.append(self.componentList[component][parkey][i]['group'])
                        i += 1
                    # if the parameter with the group has been already defined, delete it
                    else:
                        del self.componentList[component][parkey][i]

    def get_common_groups(self):
        """
        Returns a dictionary of groups shared by all components.
        :return: com_groups
        """
        # get the keys of physical parameters
        parkeys = self.get_physical_parameters()

        # get the groups
        com_groups = {}
        for key in parkeys:
            com_groups[key] = []

            # define teh reference component
            comp0 = self._registered_components[0]

            # groups are always common for one parameter
            if len(self._registered_components) < 2:
                is_common = True

            # go over each group of
            for i in range(0, len(self.componentList[comp0][key])):
                refpar = self.componentList[comp0][key][i]
                # print refpar

                # at the beginning
                for component in self._registered_components[1:]:
                    is_common = False
                    for j, par in enumerate(self.componentList[component][key]):
                        # print par
                        if refpar['group'] == par['group']:
                            is_common = True
                            break
                    if not is_common:
                        break
                if is_common:
                    com_groups[key].append(refpar['group'])

        return com_groups

    def get_components(self):
        """
        Returns list of all defined components.
        :return:
        """
        return copy.deepcopy(self._registered_components)

    def get_defined_groups(self, component=None, parameter=None):
        """:
        :param component: starlist component
        :param parameter: physical parameter
        :return: dictionary of groups
        """
        groups = {}

        # setup parameters
        if parameter is None:
            parameters = self.get_physical_parameters()
        else:
            parameters = [parameter]

        # setup components
        if component is None or component == 'all':
            components = self.get_components()
        else:
            components = [component]

        # go over the registered componentss
        for comp in components:
            groups[comp]= {}

            # go over passed parameters
            for param in parameters:
                groups[comp][param] = []
                for regparam in self.componentList[comp][param]:
                    if regparam.name == param:
                        groups[comp][param].append(regparam.group)

        # merge groups if component was 'all'
        if component == 'all':
            for p in parameters:
                groups[component] = {}
                temp = []
                for c in components:
                    # print flatten_2d(groups[c][p])
                    temp.extend(groups[c][p])
                groups[component][p] = np.unique(temp).tolist()

        return groups

    def get_fitted_parameters(self, verbose=False):
        """
        Returns a list of fitted parameters wrapped within the Parameter class ofc.
        :param verbose - return a dictionary with additional info on the
        fitted parameters.
        :return:
        """
        fit_pars = []
        # info on the fitted parameters
        # is stored in a list and passed  if
        # necessary
        if verbose:
            fit_pars_info = {'component': [], 'group': [], 'name': [], 'value': []}
        # go over all parameters and components
        for c in self._registered_components:
            for parname in self.get_physical_parameters():
                for par in self.componentList[c][parname]:
                    if par['fitted']:
                        fit_pars.append(par)
                        if verbose:
                            for k in list(fit_pars_info.keys()):
                                if k != 'component':
                                    fit_pars_info[k].append(par[k])
                                else:
                                    fit_pars_info[k].append(c)
        if not verbose:
            return fit_pars
        else:
            return fit_pars, fit_pars_info

    def get_fitted_types(self):
        """
        Stores a dictionary of fitted types for
        each component in the class. This should
        be updated whenever a parameter is changed.
        :return:
        """

        fitted_types = {}

        # go over each component
        for c in list(self.componentList.keys()):
            fitted_types[c] = []

            # go over each parameter type
            for parname in self.componentList[c]:

                # and finaly over each parameter
                for par in self.componentList[c][parname]:
                    if parname not in fitted_types[c]:
                        if par['fitted']:
                            fitted_types[c].append(parname)
                    else:
                        break

        # print fitted_types
        self.fitted_types = fitted_types

    def get_index(self, component, parameter, group):
        """
        Returns index of a component/parameter/group.
        :param component:
        :param parameter:
        :param group:
        :return:
        """

        for i, par in enumerate(self.componentList[component][parameter]):
            if par['group'] == group:
                return i

        warnings.warn('Component: %s Parameter: %s Group: %s'
                      ' not found.' % (component, parameter, str(group)))
        return None

    def get_parameter_types(self):
        """
        Returns a list of all parameter names
        :return:
        """
        partypes = []

        # go over each component and parameter
        for c in self._registered_components:
            for p in list(self.componentList[c].keys()):
                if p not in partypes:
                    partypes.append(p)
        return partypes


    def get_parameter(self, **kwargs):
        """
        Returns all parameters, which have certain group.
        :param kwargs:
        :return:
        """
        pars = {x: [] for x in self._registered_components}
        for key in list(kwargs.keys()):
            for c in self._registered_components:
                for i, par in enumerate(self.componentList[c][key]):
                    # print i, par
                    if par.group == kwargs[key]:
                        pars[c].append(self.componentList[c][key][i])

        return pars

    def get_physical_parameters(self):
        """
        Reads physical parameters from the starlist.
        :return:
        """
        pars = []
        for c in self._registered_components:
            pars.extend(list(self.componentList[c].keys()))

        return np.unique(pars)

    def list_parameters(self):
        """
        Returns a list of all parameters.s
        :return:
        """
        # empty output structure
        return copy.deepcopy(self.componentList)


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
            if l.find('STARLIST') > -1:
                data_start = i
                break

        # check that there are actually some data in the file
        if data_start >= len(lines):
            return False

        # create a StarList
        sl = StarList()

        # from here the file is actually being read
        for i, l in enumerate(lines[data_start+1:]):

            # once we reach starlist again, we end
            if l.find('STARLIST') > -1:
                break
            d = l.split()
            if d[0].find('component') > -1:
                cdict = {d[i].rstrip(':'): d[i+1] for i in range(0, len(d), 2)}

                # cast the paramneters to teh correct types
                for k in list(cdict.keys()):
                    if k in ['value', 'vmin', 'vmax']:
                        cdict[k] = float(cdict[k])
                    elif k in ['group']:
                        cdict[k] = int(cdict[k])
                    elif k in ['fitted']:
                        cdict[k] = string2bool(cdict[k])

                # add the parameter if it does not exist
                c = cdict['component']
                p = cdict['parameter']
                if c not in list(sl.componentList.keys()):
                    sl.componentList[c] = {}
                    sl._registered_components.append(c)
                if cdict['parameter'] not in list(sl.componentList[c].keys()):
                    sl.componentList[c][p] = []

                # transform the array to Parameter classs
                pdict = {key: cdict[key] for key in list(cdict.keys()) if key not in ['parameter', 'component']}
                pdict['name'] = p

                # add the parameter to teh class
                par = Parameter(**pdict)
                sl.add_parameter_to_component(component=c, p=par)

            # do the same for enviromental keys
            if d[0].find('env_keys') > -1:
                # the first string is just identification
                d = d[1:]

                # secure corrct types
                recs = ['debug']
                cast_types = [string2bool]
                cdict = {d[i].rstrip(':'): d[i+1] for i in range(0, len(d), 2)}
                for k in list(cdict.keys()):
                    if k in recs:
                        i = recs.index(k)
                        ctype = cast_types[i]
                        cdict[k] = ctype(cdict[k])

                    # assign the vlues
                    setattr(sl, k, cdict[k])

        # finally assign everything to self
        attrs = ['_registered_components', 'componentList', 'debug',
                 'fitted_types', 'groups']
        for attr in attrs:
            setattr(self, attr, getattr(sl, attr))

        # if we got here, we loaded the data
        return True

    def read_groups(self):
        """
        Reads all groups from the defined components. This
        is then compared to the list obtained from observations
        and defined regions,
        :return:
        """

        for component in list(self.componentList.keys()):
            self.groups[component] = dict()
            for key in list(self.componentList[component].keys()):
                self.groups[component][key] = []
                for par in self.componentList[component][key]:
                    self.groups[component][key].append(par['group'])

    def remove_parameter(self, component, parameter, group):
        """
        :param component: component for which the parameter is deleted
        :param parameter:deleted paramer
        :param group
        :return:
        """
        index = self.get_index(component, parameter, group)
        del self.componentList[component][parameter][index]

    def reset(self, parameters='all'):
        """
        Leaves only one parameter per type and component.
        :param parameters - list of reseted parameters
        :return:
        """
        # cycle over components
        for c in self._registered_components:

            # select all parameters
            if parameters == 'all':
                reset_params = list(self.componentList[c].keys())
            else:
                reset_params = parameters

            # cycle over reseted parameters
            for p in reset_params:
                self.componentList[c][p] = [self.componentList[c][p][0]]
                self.groups[c][p] = [self.groups[c][p][0]]


    def save(self, ofile):
        """
        Saves the class. It should be retrievable from the file.
        :param ofile:
        :return:
        """
        # Open the file
        if isinstance(ofile, str):
            ofile = open(ofile, 'w+')

        # parameters listed for each record in the starlist
        listed_keys = ['value', 'unit', 'fitted', 'vmin', 'vmax', 'group']
        string = ' STARLIST '.rjust(105, '#').ljust(200, '#') + '\n'
        for c in list(self.componentList.keys()):
            for key in list(self.componentList[c].keys()):
                for par in self.componentList[c][key]:
                    string += 'component: %s ' % c
                    string += 'parameter: %s ' % key
                    for lkey in listed_keys:
                        string += '%s: %s ' % (lkey, str(par[lkey]))
                    string += '\n'

        # setup additional parameters
        enviromental_keys = ['debug']
        string += 'env_keys: '
        for ekey in enviromental_keys:
            string += '%s: %s ' % (ekey, str(getattr(self, ekey)))
        string += '\n'
        string += ' STARLIST '.rjust(105, '#').ljust(200, '#') + '\n'
        # write the remaining parameters
        ofile.writelines(string)

    def set_groups(self, groups, overwrite=False):
        """
        Sets up groups - this function is designed to
        use output from ObservedList.get_groups().
        It is assumed that the structure is following:
        dict(component01=dict(par1=[], par2=[]), component2=..)

        This function should be used to primarily
        used to assign rv_groups, where cloning
        is necessary to not to get crazy.

        This function merges groups defined
        in the type and the one passed. In general
        we should not be able to do this.
        :param overwrite
        :param groups
        :return: None
        """

        for component in list(groups.keys()):
            for parkey in list(groups[component].keys()):

                # bool variable for case, when we want to completely overwrite
                # previous settings
                first_in_list = True

                for group in groups[component][parkey]:
                    # setting group for all components
                    if component.lower() == 'all':
                        for one_comp in self._registered_components:
                            # print one_comp, parkey, self.groups
                            if group not in self.groups[one_comp][parkey]:
                                warnings.warn("Group %s: %s previously undefined."
                                              "Adding to the remaining groups." % (parkey, str(group)))
                                # print one_comp, parkey, group
                                self.clone_parameter(one_comp, parkey, group=group)

                                # deletes all previous groups
                                if overwrite and first_in_list:
                                    while len(self.groups[one_comp][parkey]) > 1:
                                        del self.groups[one_comp][parkey][0]
                                    first_in_list = False

                    # if we are setting group only for one component
                    else:
                        if group not in self.groups[component][parkey]:
                            warnings.warn("Group %s: %s previously undefined."
                                          "Adding to the remaining groups." % (parkey, str(group)))
                            self.clone_parameter(component, parkey, group=group)

                            # deletes all previous groups
                            if overwrite and first_in_list:
                                while len(self.groups[one_comp][parkey]) > 1:
                                    del self.groups[one_comp][parkey][0]
                                first_in_list = False

    def set_parameter(self, name, component, group, **kwargs):
        """
        Sets values defined in kwargs for a parameter
        of a given component and group.
        :param name:
        :param component:
        :param group:
        :param kwargs
        :return:
        """
        # print name, component, group, kwargs
        name = name.lower()
        if name not in self.get_physical_parameters():
            raise Exception("Parameter: %s unknown." % name)
        elif component not in self._registered_components:
            # print self._registered_components, component
            raise Exception("Component: %s unknown" % component)
        elif group not in self.get_defined_groups(component, name)[component][name]:
            raise Exception("Group \"%i\" was not defined for component \"%s\" and parameter \"%s\"!" %
                            (group, component, name))
        else:
            for i, par in enumerate(self.componentList[component][name]):
                if par['name'] == name and par['group'] == group:
                    for key in list(kwargs.keys()):
                        keytest = key.lower()
                        # print name, component, keytest, kwargs[key]
                        self.componentList[component][name][i][keytest] = kwargs[key]
        # print self
        # update the list of fitted types
        self.get_fitted_types()


class SyntheticList(List):
    """
    List of resulting synthetic spectra.
    """
    def __init__(self, **kwargs):

        # initialize the parent
        super(SyntheticList, self).__init__(**kwargs)













