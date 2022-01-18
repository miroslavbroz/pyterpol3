#!/usr/bin/gnuplot

# VALD3 website; Birch & Downs (1994; Metrologie, 31, 315)
s2(lambdavac) = (1e4/lambdavac)**2
n(lambdavac) = 1.0 + 0.0000834254 + 0.02406147/(130.0-s2(lambdavac)) + 0.00015998/(38.9-s2(lambdavac))

# Husser etal. (2013); Ciddor (1996)
n2(lambdavac) = 1.0 + 0.05792105/(238.0185-s2(lambdavac)) + 0.00167917/(57.362-s2(lambdavac))

# Q: Is 6563 A value air- or vacuum-wavelength?! It's AIR!
# See https://classic.sdss.org/dr7/products/spectra/vacwavelength.html
lambdavac = 6564.614
lambdaair = lambdavac/n(lambdavac)

print "lambdavac = ", lambdavac, " A"
print "n = ", n(lambdavac)
print "lambdaair = ", lambdaair, " A"

set xl "lambda_{vac} [ang]"
set yl "n []"

set xr [3000:10000]

p n(x) lw 3,\
  n2(x) lw 3 dt 2

pa -1

set yl "lambda_{air} - lambda_{vac} [ang]"

p (n(x)-1.0)*x lw 3,\
  (n2(x)-1.0)*x lw 3 dt 2

pa -1


