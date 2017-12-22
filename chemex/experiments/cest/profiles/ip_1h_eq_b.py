"""Pure In-phase CEST.

Analyzes chemical exchange in the presence of 1H composite decoupling during
the CEST block. This keeps the spin system purely in-phase throughout, and is
calculated using the 6x6, single spin matrix:

[ Ix(a), Iy(a), Iz(a), Ix(b), Iy(b), Iz(b) ]

Notes
-----
The calculation is designed specifically to analyze the experiment found in
the reference:

J Am Chem Soc (2012), 134, 8148-8161

"""

import numpy as np
from scipy import linalg

from chemex.experiments import base_profile
from chemex.experiments.cest import cest_profile


class Profile(cest_profile.CESTProfile):
    """Profile for pure in-phase CEST."""

    def __init__(self, profile_name, measurements, exp_details):
        super().__init__(profile_name, measurements, exp_details)

        self.time_d1 = base_profile.check_par(exp_details, 'time_d1', float, 1.0)
        self.equilibrium = base_profile.check_par(exp_details, 'equilibrium', bool, False)

        if '3st' in self.model:
            from chemex.bases.three_state import ixyz_eq
        elif '4st' in self.model:
            from chemex.bases.four_state import ixyz_eq
        else:
            from chemex.bases.two_state import ixyz_eq

        self.base = ixyz_eq

        self.liouvillians_b1 = np.array(
            [self.base.compute_liouvillian(omega1x_i=omega1) for omega1 in self.omega1s])

        self.map_names, self.default_params = self.base.create_default_params(
            model=self.model,
            nuclei=self.resonance_i['name'],
            temperature=self.temperature,
            h_larmor_frq=self.h_larmor_frq,
            p_total=self.p_total,
            l_total=self.l_total, )

        for name in ('r2_i_b', 'r2_i_c', 'r2_i_d'):
            if name in self.map_names:
                param = self.default_params[self.map_names[name]]
                param.expr = self.map_names['r2_i_a']

    def calculate_unscaled_profile(self, **kwargs):
        """Calculate the CEST profile in the presence of exchange.

        TODO: Parameters
        ----------
        pb : float
            Fractional population of state B.
        kex_ab : float
            Exchange rates between states A and B in /s.
        dw_i_ab : float
            Chemical shift difference between states A and B in rad/s.
        r1_i_a : float
            Longitudinal relaxation rate of states A in /s.
        r2_i_a : float
            Transverse relaxation rate of state A in /s.
        dr2_i_ab : float
            Transverse relaxation rate difference between states A and B in /s.
        cs_i_a : float
            Resonance position of state A in ppm.

        Returns
        -------
        out : float
            Intensity after the CEST block

        """
        cs_i = np.array([kwargs.get(key, 0.0) for key in ('cs_i_a', 'cs_i_b', 'cs_i_c', 'cs_i_d')])
        omega_i_cars = (cs_i - self.carrier) * self.ppm_i

        start = self.base.index_iz_eq
        end = self.base.index_iz_b
        mesh = np.ix_(end, start)

        mag0 = self.base.compute_equilibrium_after_d1(time_d1=self.time_d1, **kwargs)

        profile = []

        for index, b1_offset in enumerate(self.b1_offsets):
            omega_i_a, omega_i_b, omega_i_c, omega_i_d = omega_i_cars - 2.0 * np.pi * b1_offset

            louvillian_nob1 = self.base.compute_liouvillian(
                omega_i_a=omega_i_a,
                omega_i_b=omega_i_b,
                omega_i_c=omega_i_c,
                omega_i_d=omega_i_d,
                **kwargs)

            liouvillians = self.liouvillians_b1 + louvillian_nob1

            if self.b1_inh == np.inf:
                s, vr = linalg.eig(liouvillians[0])
                vri = linalg.inv(vr)

                sl = [i for i, omega_i_eig in enumerate(s.imag) if abs(omega_i_eig) < 0.1]

                propagator = (vr[np.ix_(end, sl)].dot(np.diag(np.exp(s[sl] * self.time_t1)))
                              .dot(vri[np.ix_(sl, start)]))

            else:
                propagators = [
                    linalg.expm(liouvillian * self.time_t1) for liouvillian in liouvillians
                ]
                propagator = np.average(propagators, weights=self.b1_weights, axis=0)[mesh]

            magz_b = propagator.dot(mag0[start]).real

            profile.append(np.float64(magz_b))

        return np.asarray(profile)


    def filter_points(self, params=None):
        """Evaluate some criteria to know whether or not the point should be
        considered in the calculation."""
        cs = params[self.map_names['cs_i_b']].value
        nu_offsets = ((cs - self.carrier) * self.ppm_i / (2.0 * np.pi) - self.b1_offsets)

        mask = abs(nu_offsets) > self.on_resonance_filter * 0.5

        self.b1_offsets = self.b1_offsets[mask]
        self.val = self.val[mask]
        self.err = self.err[mask]
        self.reference = self.reference[mask]