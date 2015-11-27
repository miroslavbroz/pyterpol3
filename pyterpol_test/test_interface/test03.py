import pyterpol


debug=False
# 1) define some observations
ol = pyterpol.ObservedList(debug=debug)
obs = [dict(filename='o.asc', error=0.01),
       dict(filename='o2.asc', error=0.01)]
ol.add_observations(obs)
print ol

# 2) define fitted regions
rl = pyterpol.RegionList(debug=debug)
rl.add_region(wmin=4300, wmax=4380)
rl.add_region(wmin=4460, wmax=4500)

# 3) define a star
sl = pyterpol.StarList(debug=debug)
sl.add_component(component='primary', teff=20000., logg=4.5, rv=0.0, vrot=0.0, lr=1.0, z=1.0)
sl.add_component(component='secondary', teff=20000., logg=4.5, rv=0.0, vrot=0.0, lr=1.0, z=1.0)

# 4) define interface
itf = pyterpol.Interface(ol=ol, rl=rl, sl=sl, debug=True)


# 5) communicate
print itf
itf.setup_rv_groups()
print itf