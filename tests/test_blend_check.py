import unittest
import numpy as np
from punting.blend_check import fit_blend


class BlendCheckTests(unittest.TestCase):
    def test_noise_gets_no_weight_and_information_does(self):
        rng=np.random.default_rng(1)
        informative,noise=[],[]
        for _ in range(400):
            truth=rng.normal(0,1,8);p=np.exp(truth)/np.exp(truth).sum()
            y=np.zeros(8,bool);y[rng.choice(8,p=p)]=True
            junk=rng.normal(0,1,8);junk=junk-np.log(np.exp(junk).sum())
            # A model that is pure noise next to a well-informed market, and the reverse.
            noise.append((junk,np.log(p),y));informative.append((np.log(p),junk,y))
        self.assertLess(abs(fit_blend(noise)[0]),.2)
        self.assertGreater(fit_blend(informative)[0],.5)


if __name__=="__main__":unittest.main()
