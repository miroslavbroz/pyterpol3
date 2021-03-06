import warnings
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import splrep
from scipy.interpolate import splev

# repeat userwarnings
warnings.simplefilter('always', UserWarning)


class ObservedSpectrum:
    """
    A wrapper class for the observed spectra.
    """
    def __init__(self, wave=None, intens=None, error=None, filename=None,
                 component='all', korel=False, group=None, debug=False,
                 instrumental_width=0.0, **kwargs):
        """

        Setups the class.
        :param wave: wavelength vector (typically in angstrom)
        :param intens: intensity vector (typically relative)
        :param error: either error vector, or one value that will apply for whole spectrum
        :param filename: ascii (2 or 3 columns - wave, intens error) with the data
        :param component: components in the spectrum -- by default set to 'all'
        :param korel: flag defining that spectrum was obtained with KOREL - by default false
        :param group: different spectra can be grouped under certain parameter
                      e.g. group=dict(rv=1) that rv denoted by grioup one will
                      be assigned to this spectrum. This is convenient if for
                      example the same RV is assigned to a set of spectra.
        :param instrumental_width: width of the instrumental profile from which the instrumental
                     broadening is computed in Angstrom (or any other wavelength in
                     which the observed spectra are calibrated). By default it
                     is zero.
        :param hjd: Heliocentric Julian date can be assigned to each observed
                    spectrum.
        """
        # empty arrays, taht will be filled
        # with read_size
        self.wmin = None
        self.wmax = None
        self.step = None
        self.npixel = None

        # pass all arguments
        self.wave = wave
        self.intens = intens

        # lets have a look at the errors
        if error is None:
            warnings.warn("I found no array with errorbars of observed intensities. "
                          "Do not forget to assign them later!")
            self.error = None
            self.global_error = None
            self.hasErrors = False

        # sets that the spectrum is loaded
        if (wave is not None) and (intens is not None):
            self.loaded = True
            self.read_size()

            # check lengths of intens and wave
            self.check_length()

            # set the error
            if isinstance(error, (float, int)) and error is not None:
                self.error = np.ones(len(wave)) * error
                self.hasErrors = True
                self.global_error = error
            elif error is not None:
                self.error = error
                self.hasErrors = True
                self.global_error = None
        else:
            self.loaded = False

        # if we provided the filename
        self.filename = filename
        if (not self.loaded) and (self.filename is not None):
            self.read_spectrum_from_file(filename, global_error=error)
        elif (not self.loaded) and (self.filename is None):
            warnings.warn('No spectrum was loaded. This class is kinda useless without a spectrum. '
                          'I hope you know what you are doing.')

        # assignes component
        self.component = component

        # setup korel and check that it is proper
        self.korel = korel
        self.check_korel()

        # setup the group
        self.group = dict()
        if group is not None:
            self.set_group(group)

        # assigns the projected slit width
        self.instrumental_width = instrumental_width

        # setup debug mode
        self.debug = debug

        # if there is hjd passed, it is assigned to the spectrum
        self.hjd = kwargs.get('hjd', None)

    def __str__(self):
        """
        String representation of the class.
        """
        string = ''
        for var in ['filename', 'component', 'korel', 'loaded', 'hasErrors', 'global_error', 'group', 'hjd']:
            string += "%s: %s " % (var, str(getattr(self, var)))
        if self.loaded:
            string += "%s: %s " % ('(min, max)', str(self.get_boundaries()))
        string += '\n'
        return string

    def check_korel(self):
        """
        If korel is set, component must be set too.
        """
        if self.korel and str(self.component).lower() == 'all':
            raise ValueError('In the korel regime, each spectrum must be assigned component! '
                             'Currently it is set to %s.' % str(self.component))

    def check_length(self):
        """
        Checks that wavelengths and intensities have the same length.
        """
        if len(self.wave) != len(self.intens):
            raise ValueError('Wavelength vector and intensity vector do not have the same length!')

    def check_loaded(self):
        """
        Checks that spectrum is loaded.
        """
        if not self.loaded:
            raise ValueError('The spectrum is not loaded.')

    def free_spectrum(self):
        """

        Deletes the stored spectrum.
        """
        self.wave = None
        self.intens = None
        self.error = None
        self.loaded = False
        self.hasErrors = False

    def get_boundaries(self):
        """
        Returns the minimal and the maximal wavelength
        of the spectrum.
        """
        self.read_size()
        return self.wmin, self.wmax

    def get_group(self, param):
        """
        Get defined groups for a given parameter.

        :param param: the parameter
        :return: returns all groups assigned to a parameter
        """
        if param.lower() in self.group:
            return self.group[param]
        else:
            return None

    def get_instrumental_width(self):
        """

        Returns width of the instrumental profile.
        :return:
        """
        return self.instrumental_width

    def get_sigma_from_continuum(self, cmin, cmax, store=True):
        """
        Estimates the error of the flux from the scatter in
        continuum.
        :param cmin the minimal continuum value
        :param cmax the maximal continuum value
        :param store save the found error as an error
        :return stddev the standard deviation
        """
        # is the spectrum loaded ?
        self.check_loaded()

        # get the part around continue
        intens = self.get_spectrum(wmin=cmin, wmax=cmax)[1]

        # get the scatter
        stddev = intens.std(ddof=1)

        # save it as an error
        if store:
            self.global_error = stddev
            self.error = stddev * np.ones(len(self.wave))

        return stddev

    def get_sigma_from_fft(self, nlast=20, store=True):
        """
        Estimates the noise using the FFT.
        :param nlast length opf the FFT spectrum tail used to estimate the scatter
        :param store should we save the standard deviation
        """
        # check that everything is loaded
        self.check_loaded()
        self.read_size()

        # get the linear scale
        lin_wave = np.linspace(self.wmin, self.wmax, self.npixel)

        # interpolate to linear scale
        tck = splrep(self.wave, self.intens)
        lin_intens = splev(lin_wave, tck)

        # perform the FFT and shift it
        fft_intens = np.fft.fft(lin_intens)

        # get absolute values
        abs_fft_intens = np.absolute(fft_intens)

        # get the high frequency tail
        abs_fft_intens = abs_fft_intens[len(abs_fft_intens) / 2 - nlast + 1:len(abs_fft_intens) / 2 + nlast]

        # estimate the error
        stddev = abs_fft_intens.std() * abs_fft_intens.mean()

        # store the value as an erro if needed
        if store:
            self.error = stddev * np.ones(len(self.wave))
            self.global_error = stddev

        return stddev

    def get_spectrum(self, wmin=None, wmax=None):
        """

        Returns the spectrum with wavelengths wmin -> wmax
        :param wmin minimal wavelength
        :param wmax maximal wavelength
        :return wave, intens. error (optional) - the observed spectrum,
        wavelength, intensity and error (if it is given)
        """
        if not self.loaded:
            raise Exception('The spectrum %s has not been loaded yet!' % str(self))
        else:
            # the whole spectrum
            if wmin is None and wmax is None:
                if self.error is not None:
                    return self.wave.copy(), self.intens.copy(), self.error.copy()
                else:
                    return self.wave.copy(), self.intens.copy()
            else:
                # corrects boundaries if needed
                if wmin is None:
                    wmin = self.wmin
                if wmax is None:
                    wmax = self.wmax

                # What if we query too long spectrum
                if (wmin-self.wmin) < -1e-6 or (wmax - self.wmax) > 1e-6:
                    raise ValueError("Querried spectral bounds (%f %f) lie outside "
                                     "observed spectrum bounds (%f %f)." %
                                     (wmin, wmax, self.wmin, self.wmax))

                # selects the spectrum part
                ind = np.where((self.wave >= wmin) & (self.wave <= wmax))[0]

                if self.error is not None:
                    return self.wave[ind].copy(), self.intens[ind].copy(), self.error[ind].copy()
                else:
                    return self.wave[ind].copy(), self.intens[ind].copy()

    def get_wavelength(self):
        """
        Returns the wavelength vector.
        OUPUT:
          self.wave..	wavelengths
        """
        if not self.loaded:
            raise Exception('The spectrum %s has not been loaded yet!' % str(self))
        else:
            return self.wave.copy()

    def plot(self, ax=None, savefig=False, figname=None, **kwargs):
        """
        :param figname
        :param savefig
        :param ax: AxesSubplot
        :param kwargs:
        :return:
        """
        w = self.wave
        i = self.intens
        if ax is None:
            fig = plt.figure()
            ax = fig.add_subplot(111)

        props = str({'filename': self.filename, 'component': self.component, 'korel': self.korel})
        ax.plot(w, i, label=props, **kwargs)
        ax.set_xlim(self.wmin, self.wmax)
        ax.set_ylim(0.95*i.min(), 1.05*i.max())
        ax.set_xlabel('$\lambda(\AA)$')
        ax.set_ylabel('$F_{\lambda}$(rel.)')
        ax.legend(fontsize=10)

        # save the figure
        if savefig:
            if figname is None:
                figname = self.filename + '.png'

            # save the plot
            plt.savefig(figname)

    def read_size(self):
        """
        Gets the minimal wavelength, maximal wavelenbgth
        and the mean step. Linearity in wavelength is not
        required.
        """
        if not self.loaded:
            raise Exception('The spectrum %s has not been loaded yet!' % str(self))

        self.wmin = self.wave.min()
        self.wmax = self.wave.max()
        self.npixel = len(self.wave)
        self.step = np.mean(self.wave[1:] - self.wave[:-1])

    def read_spectrum_from_file(self, filename, global_error=None):
        """
        Reads the spectrum from a file. Following format
        is assumed: %f %f %f (wavelength, intensity, error).
        If user does not provide errors, we still attempt
        to load teh spectrum.
        :param filename spectrum source file
        :param global_error the error applicable to the spectrum
        :return None
        """

        # just in case we have already set up the global error
        if global_error is None and self.global_error is not None:
            global_error = self.global_error

        try:
            # first we try to load 3 columns, i.e with errors
            self.wave, self.intens, self.error = np.loadtxt(filename, unpack=True, usecols=[0, 1, 2])
            self.hasErrors = True
        except:
            # we failed, so we attempt to load two columns
            self.wave, self.intens = np.loadtxt(filename, unpack=True, usecols=[0, 1])

            # error was not set up
            if global_error is None:
                warnings.warn("I found no errorbars of the observed intensities in file: %s! "
                              "I assume they will be provided later. I remember!!" % filename)
                self.hasErrors = False
                self.global_error = None

            # error was set up
            else:
                self.error = global_error * np.ones(len(self.wave))
                self.hasErrors = True
                self.global_error = global_error

        # the spectrum is marked as loaded
        self.loaded = True

        # the spectrum is checked
        self.check_length()
        self.read_size()

    def reload_spectrum(self):
        """
        Reloads the spectrum.
        :return:
        """
        if self.loaded is False:
            warnings.warn('The spectrum was not loaded, so I am not reloading, but loading... just FYI.')
        if self.filename is None:
            raise ValueError('There has been no spectrum given for %s' % (str(self)))

        self.read_spectrum_from_file(self.filename)

    def select_random_subset(self, frac):
        """
        :param frac: sepctrum fraction 0.0-1.0
        :return:
        """

        if not self.loaded:
            raise AttributeError('Cannost select a subset. '
                                 'The spectrum %s has not been loaded yet.' % (str(self)))

        # set the newlength
        newlength = int(np.ceil(frac*self.npixel))

        if newlength >= self.npixel:
            return

        # surviving spectra indices
        inds = np.sort(np.random.randint(self.npixel, size=newlength))

        # adjustr the spectra
        self.wave = self.wave[inds]
        self.intens = self.intens[inds]
        if self.error is not None:
            self.error = self.error[inds]

        # measure the spectrum
        self.read_size()

    def set_error(self, vec_error=None, global_error=None):
        """
        Sets error to the spectrum..either local or global.
        :param vec_error vector error len(vec_error) = len(spectrum)
        :param global_error int float error applied to the whole spectrum
        """
        if vec_error is not None:
            self.error = vec_error
            if len(vec_error) != len(self.npixel):
                raise ValueError('The lenght of the error vector and the length of the spectrum do not match (%s, %s)'
                                 % (len(vec_error), str(self.npixel)))
            self.hasErrors = True
            self.global_error = None
        if global_error is not None:
            self.error = global_error * np.ones(len(self.wave))
            self.hasErrors = True
            self.global_error = global_error

    def set_group(self, group):
        """
        Sets a group to the spectrum
        :param group a dictionary of pairs parameter + group
        """
        # print group
        for key in list(group.keys()):
            self.group[key.lower()] = group[key]

    def set_spectrum_from_arrays(self, wave, intens, error):
        """
        Stores the spectrum from arrays. It is assumed
        that user also provides error vector.
        :param wave wavelength vector
        :param intens intensity vector
        :param error eror vector
        """
        self.wave = wave
        self.intens = intens
        self.error = error
        self.loaded = True
        self.hasErrors = True

        # checking and reading
        self.check_length()
        self.read_size()
