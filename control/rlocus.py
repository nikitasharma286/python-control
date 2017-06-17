# rlocus.py - code for computing a root locus plot
# Code contributed by Ryan Krauss, 2010
#
# Copyright (c) 2010 by Ryan Krauss
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the California Institute of Technology nor
#    the names of its contributors may be used to endorse or promote
#    products derived from this software without specific prior
#    written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL CALTECH
# OR THE CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#
# RMM, 17 June 2010: modified to be a standalone piece of code
#   * Added BSD copyright info to file (per Ryan)
#   * Added code to convert (num, den) to poly1d's if they aren't already.
#     This allows Ryan's code to run on a standard signal.ltisys object
#     or a control.TransferFunction object.
#   * Added some comments to make sure I understand the code
#
# RMM, 2 April 2011: modified to work with new LTI structure (see ChangeLog)
#   * Not tested: should still work on signal.ltisys objects
#
# $Id$

# Packages used by this module
import numpy as np
from scipy import array, poly1d, row_stack, zeros_like, real, imag
import scipy.signal             # signal processing toolbox
import pylab                    # plotting routines
from .xferfcn import _convertToTransferFunction
from .exception import ControlMIMONotImplemented
from functools import partial

__all__ = ['root_locus', 'rlocus']


# Main function: compute a root locus diagram
def root_locus(sys, kvect=None, xlim=None, ylim=None, plotstr='-', Plot=True,
               PrintGain=True, grid=False):
    """Root locus plot

    Calculate the root locus by finding the roots of 1+k*TF(s)
    where TF is self.num(s)/self.den(s) and each k is an element
    of kvect.

    Parameters
    ----------
    sys : LTI object
        Linear input/output systems (SISO only, for now)
    kvect : list or ndarray, optional
        List of gains to use in computing diagram
    xlim : tuple or list, optional
        control of x-axis range, normally with tuple (see matplotlib.axes)
    ylim : tuple or list, optional
        control of y-axis range
    Plot : boolean, optional (default = True)
        If True, plot root locus diagram.
    PrintGain: boolean (default = True)
        If True, report mouse clicks when close to the root-locus branches,
        calculate gain, damping and print
    grid: boolean (default = False)
        If True plot s-plane grid. 

    Returns
    -------
    rlist : ndarray
        Computed root locations, given as a 2d array
    klist : ndarray or list
        Gains used.  Same as klist keyword argument if provided.
    """

    # Convert numerator and denominator to polynomials if they aren't
    (nump, denp) = _systopoly1d(sys)

    if kvect is None:
        kvect, mymat, xlim, ylim = _default_gains(nump, denp, xlim, ylim)
    else:
        mymat = _RLFindRoots(nump, denp, kvect)
        mymat = _RLSortRoots(mymat)

    # Create the Plot
    if Plot:
        figure_number = pylab.get_fignums()
        figure_title = [pylab.figure(numb).canvas.get_window_title() for numb in figure_number]
        new_figure_name = "Root Locus"
        rloc_num = 1
        while new_figure_name in figure_title:
            new_figure_name = "Root Locus " + str(rloc_num)
            rloc_num += 1
        f = pylab.figure(new_figure_name)

        if PrintGain:
            f.canvas.mpl_connect(
                'button_release_event', partial(_RLFeedbackClicks, sys=sys))
        ax = pylab.axes()

        # plot open loop poles
        poles = array(denp.r)
        ax.plot(real(poles), imag(poles), 'x')

        # plot open loop zeros
        zeros = array(nump.r)
        if zeros.size > 0:
            ax.plot(real(zeros), imag(zeros), 'o')

        # Now plot the loci
        for col in mymat.T:
            ax.plot(real(col), imag(col), plotstr)

        # Set up plot axes and labels
        if xlim:
            ax.set_xlim(xlim)
        if ylim:
            ax.set_ylim(ylim)
        ax.set_xlabel('Real')
        ax.set_ylabel('Imaginary')
        if grid:
            _sgrid_func()
    return mymat, kvect


def _default_gains(num, den, xlim, ylim):
    """Unsupervised gains calculation for root locus plot. 
    
    References:
     Ogata, K. (2002). Modern control engineering (4th ed.). Upper Saddle River, NJ : New Delhi: Prentice Hall.."""

    k_break, real_break = _break_points(num, den)
    kmax = _k_max(num, den, real_break, k_break)
    kvect = np.hstack((np.linspace(0, kmax, 50), np.real(k_break)))
    kvect.sort()
    mymat = _RLFindRoots(num, den, kvect)
    mymat = _RLSortRoots(mymat)
    open_loop_poles = den.roots
    open_loop_zeros = num.roots

    if (open_loop_zeros.size != 0) & (open_loop_zeros.size < open_loop_poles.size):
        open_loop_zeros_xl = np.append(open_loop_zeros,
                                       np.ones(open_loop_poles.size - open_loop_zeros.size) * open_loop_zeros[-1])
        mymat_xl = np.append(mymat, open_loop_zeros_xl)
    else:
        mymat_xl = mymat
    singular_points = np.concatenate((num.roots, den.roots), axis=0)
    important_points = np.concatenate((singular_points, real_break), axis=0)
    important_points = np.concatenate((important_points, np.zeros(2)), axis=0)
    mymat_xl = np.append(mymat_xl, important_points)
    false_gain = den.coeffs[0] / num.coeffs[0]
    if false_gain < 0 and not den.order > num.order:
        raise ValueError("Not implemented support for 0 degrees root "
                         "locus with equal order of numerator and denominator.")

    if xlim is None and false_gain > 0:
        x_tolerance = 0.05 * (np.max(np.real(mymat_xl)) - np.min(np.real(mymat_xl)))
        xlim = _ax_lim(mymat_xl)
    elif xlim is None and false_gain < 0:
        axmin = np.min(np.real(important_points))-(np.max(np.real(important_points))-np.min(np.real(important_points)))
        axmin = np.min(np.array([axmin, np.min(np.real(mymat_xl))]))
        axmax = np.max(np.real(important_points))+np.max(np.real(important_points))-np.min(np.real(important_points))
        axmax = np.max(np.array([axmax, np.max(np.real(mymat_xl))]))
        xlim = [axmin, axmax]
        x_tolerance = 0.05 * (axmax - axmin)
    else:
        x_tolerance = 0.05 * (xlim[1] - xlim[0])

    if ylim is None:
        y_tolerance = 0.05 * (np.max(np.imag(mymat_xl)) - np.min(np.imag(mymat_xl)))
        ylim = _ax_lim(mymat_xl * 1j)
    else:
        y_tolerance = 0.05 * (ylim[1] - ylim[0])


    tolerance = np.max([x_tolerance, y_tolerance])
    distance_points = np.abs(np.diff(mymat, axis=0))
    indexes_too_far = np.where(distance_points > tolerance)

    while (indexes_too_far[0].size > 0) & (kvect.size < 5000):
        for index in indexes_too_far[0]:
            new_gains = np.linspace(kvect[index], kvect[index+1], 5)
            new_points = _RLFindRoots(num, den, new_gains[1:4])
            kvect = np.insert(kvect, index+1, new_gains[1:4])
            mymat = np.insert(mymat, index+1, new_points, axis=0)

        mymat = _RLSortRoots(mymat)
        distance_points = np.abs(np.diff(mymat, axis=0)) > tolerance  # distance between points
        indexes_too_far = np.where(distance_points)

    new_gains = np.hstack((np.linspace(kvect[-1], kvect[-1]*1e10, 10)))
    new_points = _RLFindRoots(num, den, new_gains[1:10])
    kvect = np.append(kvect, new_gains[1:10])
    mymat = np.concatenate((mymat, new_points), axis=0)
    mymat = _RLSortRoots(mymat)
    return kvect, mymat, xlim, ylim


def _break_points(num, den):
    """Extract break points over real axis and the gains give these location"""
    # type: (np.poly1d, np.poly1d) -> (np.array, np.array)
    dnum = num.deriv(m=1)
    dden = den.deriv(m=1)
    polynom = den * dnum - num * dden
    real_break_pts = polynom.r
    real_break_pts = real_break_pts[num(real_break_pts) != 0]  # don't care about infinite break points
    k_break = -den(real_break_pts) / num(real_break_pts)
    idx = k_break >= 0   # only positives gains
    k_break = k_break[idx]
    real_break_pts = real_break_pts[idx]
    if len(k_break) == 0:
        k_break = [0]
        real_break_pts = den.roots
    return k_break, real_break_pts


def _ax_lim(mymat):
    """Utility to get the axis limits"""
    axmin = np.min(np.real(mymat))
    axmax = np.max(np.real(mymat))
    if axmax != axmin:
        deltax = (axmax - axmin) * 0.02
    else:
        deltax = np.max([1., axmax / 2])
    axlim = [axmin - deltax, axmax + deltax]
    return axlim


def _k_max(num, den, real_break_points, k_break_points):
    """" Calculation the maximum gain for the root locus shown in tne figure"""
    asymp_number = den.order - num.order
    singular_points = np.concatenate((num.roots, den.roots), axis=0)
    important_points = np.concatenate((singular_points, real_break_points), axis=0)
    false_gain = den.coeffs[0] / num.coeffs[0]

    if asymp_number > 0:
        asymp_center = (np.sum(den.roots) - np.sum(num.roots))/asymp_number
        distance_max = 4 * np.max(np.abs(important_points - asymp_center))
        asymp_angles = (2 * np.arange(0, asymp_number)-1) * np.pi / asymp_number
        if false_gain > 0:
            farthest_points = asymp_center + distance_max * np.exp(asymp_angles * 1j)  # farthest points over asymptotes
        else:
            asymp_angles = asymp_angles + np.pi
            farthest_points = asymp_center + distance_max * np.exp(asymp_angles * 1j)  # farthest points over asymptotes
        kmax_asymp = np.real(np.abs(den(farthest_points) / num(farthest_points)))
    else:
        kmax_asymp = np.abs([np.abs(den.coeffs[0]) / np.abs(num.coeffs[0]) * 3])

    kmax = np.max(np.concatenate((np.real(kmax_asymp), np.real(k_break_points)), axis=0))
    kmax = np.max([kmax, np.abs(false_gain)])
    return kmax


def _systopoly1d(sys):
    """Extract numerator and denominator polynomails for a system"""
    # Allow inputs from the signal processing toolbox
    if (isinstance(sys, scipy.signal.lti)):
        nump = sys.num
        denp = sys.den

    else:
        # Convert to a transfer function, if needed
        sys = _convertToTransferFunction(sys)

        # Make sure we have a SISO system
        if (sys.inputs > 1 or sys.outputs > 1):
            raise ControlMIMONotImplemented()

        # Start by extracting the numerator and denominator from system object
        nump = sys.num[0][0]
        denp = sys.den[0][0]

    # Check to see if num, den are already polynomials; otherwise convert
    if (not isinstance(nump, poly1d)):
        nump = poly1d(nump)

    if (not isinstance(denp, poly1d)):
        denp = poly1d(denp)

    return (nump, denp)


def _RLFindRoots(nump, denp, kvect):
    """Find the roots for the root locus."""

    # Convert numerator and denominator to polynomials if they aren't
    roots = []
    for k in kvect:
        curpoly = denp + k * nump
        curroots = curpoly.r
        if len(curroots) < denp.order:
            curroots = np.insert(curroots, len(curroots), np.inf)  # if i have less poles than open loop is because  i
            #  have one in infinity

        curroots.sort()
        roots.append(curroots)

    mymat = row_stack(roots)
    return mymat


def _RLSortRoots(mymat):
    """Sort the roots from sys._RLFindRoots, so that the root
    locus doesn't show weird pseudo-branches as roots jump from
    one branch to another."""

    sorted = zeros_like(mymat)
    for n, row in enumerate(mymat):
        if n == 0:
            sorted[n, :] = row
        else:
            # sort the current row by finding the element with the
            # smallest absolute distance to each root in the
            # previous row
            available = list(range(len(prevrow)))
            for elem in row:
                evect = elem-prevrow[available]
                ind1 = abs(evect).argmin()
                ind = available.pop(ind1)
                sorted[n, ind] = elem
        prevrow = sorted[n, :]
    return sorted


def _RLFeedbackClicks(event, sys):
    """Print root-locus gain feedback for clicks on the root-locus plot
    """
    s = complex(event.xdata, event.ydata)
    K = -1./sys.horner(s)
    if abs(K.real) > 1e-8 and abs(K.imag/K.real) < 0.04:
        print("Clicked at %10.4g%+10.4gj gain %10.4g damp %10.4g" %
              (s.real, s.imag, K.real, -1 * s.real / abs(s)))


def _sgrid_func(fig=None, zeta=None, wn=None):
    if fig is None:
        fig = pylab.gcf()
    ax = fig.gca()
    ylocator = ax.get_yaxis().get_major_locator()
    xlocator = ax.get_xaxis().get_major_locator()

    ylim = ax.get_ylim()
    ytext_pos_lim = ylim[1] - (ylim[1] - ylim[0]) * 0.03
    xlim = ax.get_xlim()
    xtext_pos_lim = xlim[0] + (xlim[1] - xlim[0]) * 0.0

    if zeta is None:
        zeta = _default_zetas(xlim, ylim)

    angules = []
    for z in zeta:
        if (z >= 1e-4) & (z <= 1):
            angules.append(np.pi/2 + np.arcsin(z))
        else:
            zeta.remove(z)
    y_over_x = np.tan(angules)

    # zeta-constant lines

    index = 0

    for yp in y_over_x:
        ax.plot([0, xlocator()[0]], [0, yp*xlocator()[0]], color='gray',
                linestyle='dashed', linewidth=0.5)
        ax.plot([0, xlocator()[0]], [0, -yp * xlocator()[0]], color='gray',
                linestyle='dashed', linewidth=0.5)
        an = "%.2f" % zeta[index]
        if yp < 0:
            xtext_pos = 1/yp * ylim[1]
            ytext_pos = yp * xtext_pos_lim
            if np.abs(xtext_pos) > np.abs(xtext_pos_lim):
                xtext_pos = xtext_pos_lim
            else:
                ytext_pos = ytext_pos_lim
            ax.annotate(an, textcoords='data', xy=[xtext_pos, ytext_pos], fontsize=8)
        index += 1
    ax.plot([0, 0], [ylim[0], ylim[1]], color='gray', linestyle='dashed', linewidth=0.5)

    angules = np.linspace(-90, 90, 20)*np.pi/180
    if wn is None:
        wn = _default_wn(xlocator(), ylim)

    for om in wn:
        if om < 0:
            yp = np.sin(angules)*np.abs(om)
            xp = -np.cos(angules)*np.abs(om)
            ax.plot(xp, yp, color='gray',
                    linestyle='dashed', linewidth=0.5)
            an = "%.2f" % -om
            ax.annotate(an, textcoords='data', xy=[om, 0], fontsize=8)


def _default_zetas(xlim, ylim):
    """Return default list of dumps coefficients"""
    sep1 = -xlim[0]/4
    ang1 = [np.arctan((sep1*i)/ylim[1]) for i in np.arange(1,4,1)]
    sep2 = ylim[1] / 3
    ang2 = [np.arctan(-xlim[0]/(ylim[1]-sep2*i)) for i in np.arange(1,3,1)]

    angules = np.concatenate((ang1, ang2))
    angules = np.insert(angules, len(angules), np.pi/2)
    zeta = np.sin(angules)
    return zeta.tolist()


def _default_wn(xloc, ylim):
    """Return default wn for root locus plot"""

    wn = xloc
    sep = xloc[1]-xloc[0]
    while np.abs(wn[0]) < ylim[1]:
        wn = np.insert(wn, 0, wn[0]-sep)

    while len(wn)>7:
        wn = wn[0:-1:2]

    return wn

rlocus = root_locus
