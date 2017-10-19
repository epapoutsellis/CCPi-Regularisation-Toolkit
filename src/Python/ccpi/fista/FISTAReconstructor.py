# -*- coding: utf-8 -*-
###############################################################################
#This work is part of the Core Imaging Library developed by
#Visual Analytics and Imaging System Group of the Science Technology
#Facilities Council, STFC
#
#Copyright 2017 Edoardo Pasca, Srikanth Nagella
#Copyright 2017 Daniil Kazantsev
#
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#http://www.apache.org/licenses/LICENSE-2.0
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.
###############################################################################



import numpy
#from ccpi.reconstruction.parallelbeam import alg

#from ccpi.imaging.Regularizer import Regularizer
from enum import Enum

import astra

   
    
class FISTAReconstructor():
    '''FISTA-based reconstruction algorithm using ASTRA-toolbox
    
    '''
    # <<<< FISTA-based reconstruction algorithm using ASTRA-toolbox >>>>
    # ___Input___:
    # params.[] file:
    #       - .proj_geom (geometry of the projector) [required]
    #       - .vol_geom (geometry of the reconstructed object) [required]
    #       - .sino (vectorized in 2D or 3D sinogram) [required]
    #       - .iterFISTA (iterations for the main loop, default 40)
    #       - .L_const (Lipschitz constant, default Power method)                                                                                                    )
    #       - .X_ideal (ideal image, if given)
    #       - .weights (statisitcal weights, size of the sinogram)
    #       - .ROI (Region-of-interest, only if X_ideal is given)
    #       - .initialize (a 'warm start' using SIRT method from ASTRA)
    #----------------Regularization choices------------------------
    #       - .Regul_Lambda_FGPTV (FGP-TV regularization parameter)
    #       - .Regul_Lambda_SBTV (SplitBregman-TV regularization parameter)
    #       - .Regul_Lambda_TVLLT (Higher order SB-LLT regularization parameter)
    #       - .Regul_tol (tolerance to terminate regul iterations, default 1.0e-04)
    #       - .Regul_Iterations (iterations for the selected penalty, default 25)
    #       - .Regul_tauLLT (time step parameter for LLT term)
    #       - .Ring_LambdaR_L1 (regularization parameter for L1-ring minimization, if lambdaR_L1 > 0 then switch on ring removal)
    #       - .Ring_Alpha (larger values can accelerate convergence but check stability, default 1)
    #----------------Visualization parameters------------------------
    #       - .show (visualize reconstruction 1/0, (0 default))
    #       - .maxvalplot (maximum value to use for imshow[0 maxvalplot])
    #       - .slice (for 3D volumes - slice number to imshow)
    # ___Output___:
    # 1. X - reconstructed image/volume
    # 2. output - a structure with
    #    - .Resid_error - residual error (if X_ideal is given)
    #    - .objective: value of the objective function
    #    - .L_const: Lipshitz constant to avoid recalculations
    
    # References:
    # 1. "A Fast Iterative Shrinkage-Thresholding Algorithm for Linear Inverse
    # Problems" by A. Beck and M Teboulle
    # 2. "Ring artifacts correction in compressed sensing..." by P. Paleo
    # 3. "A novel tomographic reconstruction method based on the robust
    # Student's t function for suppressing data outliers" D. Kazantsev et.al.
    # D. Kazantsev, 2016-17
    def __init__(self, projector_geometry, output_geometry, input_sinogram,
                 **kwargs):
        # handle parmeters:
        # obligatory parameters
        self.pars = dict()
        self.pars['projector_geometry'] = projector_geometry # proj_geom
        self.pars['output_geometry'] = output_geometry       # vol_geom
        self.pars['input_sinogram'] = input_sinogram         # sino
        sliceZ, nangles, detectors = numpy.shape(input_sinogram)
        self.pars['detectors'] = detectors
        self.pars['number_of_angles'] = nangles
        self.pars['SlicesZ'] = sliceZ

        print (self.pars)
        # handle optional input parameters (at instantiation)
        
        # Accepted input keywords
        kw = (
              # mandatory fields
              'projector_geometry',
              'output_geometry',
              'input_sinogram',
              'detectors',
              'number_of_angles',
              'SlicesZ',
              # optional fields
              'number_of_iterations', 
              'Lipschitz_constant' , 
              'ideal_image' ,
              'weights' , 
              'region_of_interest' , 
              'initialize' , 
              'regularizer' , 
              'ring_lambda_R_L1',
              'ring_alpha',
              'subsets',
              'use_studentt_fidelity',
              'studentt')
        self.acceptedInputKeywords = list(kw)
        
        # handle keyworded parameters
        if kwargs is not None:
            for key, value in kwargs.items():
                if key in kw:
                    #print("{0} = {1}".format(key, value))                        
                    self.pars[key] = value
                    
        # set the default values for the parameters if not set
        if 'number_of_iterations' in kwargs.keys():
            self.pars['number_of_iterations'] = kwargs['number_of_iterations']
        else:
            self.pars['number_of_iterations'] = 40
        if 'weights' in kwargs.keys():
            self.pars['weights'] = kwargs['weights']
        else:
            self.pars['weights'] = \
                                 numpy.ones(numpy.shape(
                                     self.pars['input_sinogram']))
        if 'Lipschitz_constant' in kwargs.keys():
            self.pars['Lipschitz_constant'] = kwargs['Lipschitz_constant']
        else:
            self.pars['Lipschitz_constant'] = None
        
        if not 'ideal_image' in kwargs.keys():
            self.pars['ideal_image'] = None
        
        if not 'region_of_interest'in kwargs.keys() :
            if self.pars['ideal_image'] == None:
                pass
            else:
                self.pars['region_of_interest'] = numpy.nonzero(
                    self.pars['ideal_image']>0.0)
                
        # the regularizer must be a correctly instantiated object    
        if not 'regularizer' in kwargs.keys() :
            self.pars['regularizer'] = None

        #RING REMOVAL
        if not 'ring_lambda_R_L1' in kwargs.keys():
            self.pars['ring_lambda_R_L1'] = 0
        if not 'ring_alpha' in kwargs.keys():
            self.pars['ring_alpha'] = 1

        # ORDERED SUBSET
        if not 'subsets' in kwargs.keys():
            self.pars['subsets'] = 0
        else:
            self.createOrderedSubsets()

        if not 'initialize' in kwargs.keys():
            self.pars['initialize'] = False

        if not 'use_studentt_fidelity' in kwargs.keys():
            self.setParameter(studentt=False)
        else:
            print ("studentt {0}".format(kwargs['use_studentt_fidelity']))
            if kwargs['use_studentt_fidelity']:
                raise Exception('Not implemented')
            
            self.setParameter(studentt=kwargs['use_studentt_fidelity'])
            
            
    def setParameter(self, **kwargs):
        '''set named parameter for the reconstructor engine
        
        raises Exception if the named parameter is not recognized
        
        '''
        for key , value in kwargs.items():
            if key in self.acceptedInputKeywords:
                if key == 'use_studentt_fidelity':
                    raise Exception('use_studentt_fidelity Not implemented')
                self.pars[key] = value
            else:
                raise Exception('Wrong parameter {0} for '.format(key) +
                                'reconstructor')
    # setParameter

    def getParameter(self, key):
        if type(key) is str:
            if key in self.acceptedInputKeywords:
                return self.pars[key]
            else:
                raise Exception('Unrecongnised parameter: {0} '.format(key) )
        elif type(key) is list:
            outpars = []
            for k in key:
                outpars.append(self.getParameter(k))
            return outpars
        else:
            raise Exception('Unhandled input {0}' .format(str(type(key))))
            
    
    def calculateLipschitzConstantWithPowerMethod(self):
        ''' using Power method (PM) to establish L constant'''
        
        N = self.pars['output_geometry']['GridColCount']
        proj_geom = self.pars['projector_geometry']
        vol_geom = self.pars['output_geometry']
        weights = self.pars['weights']
        SlicesZ = self.pars['SlicesZ']
        
            
                               
        if (proj_geom['type'] == 'parallel') or \
           (proj_geom['type'] == 'parallel3d'):
            #% for parallel geometry we can do just one slice
            #print('Calculating Lipshitz constant for parallel beam geometry...')
            niter = 5;# % number of iteration for the PM
            #N = params.vol_geom.GridColCount;
            #x1 = rand(N,N,1);
            x1 = numpy.random.rand(1,N,N)
            #sqweight = sqrt(weights(:,:,1));
            sqweight = numpy.sqrt(weights[0])
            proj_geomT = proj_geom.copy();
            proj_geomT['DetectorRowCount'] = 1;
            vol_geomT = vol_geom.copy();
            vol_geomT['GridSliceCount'] = 1;
            
            #[sino_id, y] = astra_create_sino3d_cuda(x1, proj_geomT, vol_geomT);
            
            
            for i in range(niter):
            #        [id,x1] = astra_create_backprojection3d_cuda(sqweight.*y, proj_geomT, vol_geomT);
            #            s = norm(x1(:));
            #            x1 = x1/s;
            #            [sino_id, y] = astra_create_sino3d_cuda(x1, proj_geomT, vol_geomT);
            #            y = sqweight.*y;
            #            astra_mex_data3d('delete', sino_id);
            #            astra_mex_data3d('delete', id);
                #print ("iteration {0}".format(i))
                                
                sino_id, y = astra.creators.create_sino3d_gpu(x1,
                                                          proj_geomT,
                                                          vol_geomT)
                
                y = (sqweight * y).copy() # element wise multiplication
                
                #b=fig.add_subplot(2,1,2)
                #imgplot = plt.imshow(x1[0])
                #plt.show()
                
                #astra_mex_data3d('delete', sino_id);
                astra.matlab.data3d('delete', sino_id)
                del x1
                    
                idx,x1 = astra.creators.create_backprojection3d_gpu((sqweight*y).copy(), 
                                                                    proj_geomT,
                                                                    vol_geomT)
                del y
                
                                                                    
                s = numpy.linalg.norm(x1)
                ### this line?
                x1 = (x1/s).copy();
                
            #        ### this line?
            #        sino_id, y = astra.creators.create_sino3d_gpu(x1, 
            #                                                      proj_geomT, 
            #                                                      vol_geomT);
            #        y = sqweight * y;
                astra.matlab.data3d('delete', sino_id);
                astra.matlab.data3d('delete', idx)
                print ("iteration {0} s= {1}".format(i,s))
                
            #end
            del proj_geomT
            del vol_geomT
            #plt.show()
        else:
            #% divergen beam geometry
            print('Calculating Lipshitz constant for divergen beam geometry...')
            niter = 8; #% number of iteration for PM
            x1 = numpy.random.rand(SlicesZ , N , N);
            #sqweight = sqrt(weights);
            sqweight = numpy.sqrt(weights[0])
            
            sino_id, y = astra.creators.create_sino3d_gpu(x1, proj_geom, vol_geom);
            y = sqweight*y;
            #astra_mex_data3d('delete', sino_id);
            astra.matlab.data3d('delete', sino_id);
            
            for i in range(niter):
                #[id,x1] = astra_create_backprojection3d_cuda(sqweight.*y, proj_geom, vol_geom);
                idx,x1 = astra.creators.create_backprojection3d_gpu(sqweight*y, 
                                                                    proj_geom, 
                                                                    vol_geom)
                s = numpy.linalg.norm(x1)
                ### this line?
                x1 = x1/s;
                ### this line?
                #[sino_id, y] = astra_create_sino3d_gpu(x1, proj_geom, vol_geom);
                sino_id, y = astra.creators.create_sino3d_gpu(x1, 
                                                              proj_geom, 
                                                              vol_geom);
                
                y = sqweight*y;
                #astra_mex_data3d('delete', sino_id);
                #astra_mex_data3d('delete', id);
                astra.matlab.data3d('delete', sino_id);
                astra.matlab.data3d('delete', idx);
            #end
            #clear x1
            del x1

        
        return s
    
    
    def setRegularizer(self, regularizer):
        if regularizer is not None:
            self.pars['regularizer'] = regularizer
        

    def initialize(self):
        # convenience variable storage
        proj_geom = self.pars['projector_geometry']
        vol_geom = self.pars['output_geometry']
        sino = self.pars['input_sinogram']
        
        # a 'warm start' with SIRT method
        # Create a data object for the reconstruction
        rec_id = astra.matlab.data3d('create', '-vol',
                                    vol_geom);
        
        #sinogram_id = astra_mex_data3d('create', '-proj3d', proj_geom, sino);
        sinogram_id = astra.matlab.data3d('create', '-proj3d',
                                          proj_geom,
                                          sino)

        sirt_config = astra.astra_dict('SIRT3D_CUDA')
        sirt_config['ReconstructionDataId' ] = rec_id
        sirt_config['ProjectionDataId'] = sinogram_id

        sirt = astra.algorithm.create(sirt_config)
        astra.algorithm.run(sirt, iterations=35)
        X = astra.matlab.data3d('get', rec_id)

        # clean up memory
        astra.matlab.data3d('delete', rec_id)
        astra.matlab.data3d('delete', sinogram_id)
        astra.algorithm.delete(sirt)

        

        return X

    def createOrderedSubsets(self, subsets=None):
        if subsets is None:
            try:
                subsets = self.getParameter('subsets')
            except Exception():
                subsets = 0
            #return subsets

        angles = self.getParameter('projector_geometry')['ProjectionAngles'] 
        
        #binEdges = numpy.linspace(angles.min(),
        #                          angles.max(),
        #                          subsets + 1)
        binsDiscr, binEdges = numpy.histogram(angles, bins=subsets)
        # get rearranged subset indices
        IndicesReorg = numpy.zeros((numpy.shape(angles)))
        counterM = 0
        for ii in range(binsDiscr.max()):
            counter = 0
            for jj in range(subsets):
                curr_index = ii + jj  + counter
                #print ("{0} {1} {2}".format(binsDiscr[jj] , ii, counterM))
                if binsDiscr[jj] > ii:
                    if (counterM < numpy.size(IndicesReorg)):
                        IndicesReorg[counterM] = curr_index
                    counterM = counterM + 1
                    
                counter = counter + binsDiscr[jj] - 1    
                
            
        return IndicesReorg
            

    def prepareForIteration(self):
        self.residual_error = numpy.zeros((self.pars['number_of_iterations']))
        self.objective = numpy.zeros((self.pars['number_of_iterations']))

        #2D array (for 3D data) of sparse "ring" 
        detectors, nangles, sliceZ  = numpy.shape(self.pars['input_sinogram'])
        self.r = numpy.zeros((detectors, sliceZ), dtype=numpy.float)
        # another ring variable
        self.r_x = self.r.copy()

        self.residual = numpy.zeros(numpy.shape(self.pars['input_sinogram']))
        
        if self.getParameter('Lipschitz_constant') is None:
            self.pars['Lipschitz_constant'] = \
                            self.calculateLipschitzConstantWithPowerMethod()
        

    # prepareForIteration

    def iterate(self, Xin=None):
        # convenience variable storage
        proj_geom , vol_geom, sino , \
                  SlicesZ = self.getParameter([ 'projector_geometry' ,
                                                'output_geometry',
                                                'input_sinogram',
                                                'SlicesZ'])
                        
        t = 1
        if Xin is None:    
            if self.getParameter('initialize'):
                X = self.initialize()
            else:
                N = vol_geom['GridColCount']
                X = numpy.zeros((N,N,SlicesZ), dtype=numpy.float)
        else:
            # copy by reference
            X = Xin

        X_t = X.copy()
        
        for i in range(self.getParameter('number_of_iterations')):
            X_old = X.copy()
            t_old = t
            r_old = self.r.copy()
            if self.getParameter('projector_geometry')['type'] == 'parallel' or \
               self.getParameter('projector_geometry')['type'] == 'parallel3d':
                # if the geometry is parallel use slice-by-slice
                # projection-backprojection routine
                #sino_updt = zeros(size(sino),'single');
                proj_geomT = proj_geom.copy()
                proj_geomT['DetectorRowCount'] = 1
                vol_geomT = vol_geom.copy()
                vol_geomT['GridSliceCount'] = 1;
                sino_updt = numpy.zeros(numpy.shape(sino), dtype=numpy.float)
                for kkk in range(SlicesZ):
                    print (kkk)
                    sino_id, sino_updt[kkk] = \
                             astra.creators.create_sino3d_gpu(
                                 X_t[kkk:kkk+1], proj_geomT, vol_geomT)
                    astra.matlab.data3d('delete', sino_id)
            else:
                # for divergent 3D geometry (watch the GPU memory overflow in
                # ASTRA versions < 1.8)
                #[sino_id, sino_updt] = astra_create_sino3d_cuda(X_t, proj_geom, vol_geom);
                sino_id, sino_updt = astra.matlab.create_sino3d_gpu(
                    X_t, proj_geom, vol_geom)


            ## RING REMOVAL

            ## REGULARIZATION
            