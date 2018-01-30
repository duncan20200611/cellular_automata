from functools import lru_cache

import itertools as it # for cartesian product
import random
import os
import logging
# import argparse
import numpy as np
# import matplotlib.pyplot as plt

class automaton:
    def __init__(self, args):
        self.npeds = args.numPeds
        # drawing parameter
        self.drawS = args.plotS  # plot or not
        self.drawP = args.plotP  # plot or not
        self.drawD = args.plotD
        self.drawD_avg = args.plotAvgD
        # model parameter
        self.kappaS = args.ks
        self.kappaD = args.kd
        self.delta = args.decay
        self.alpha = args.diffusion
        self.moore = args.moore
        # Update parameter
        self.shuffle = args.shuffle
        self.reverse = args.reverse
        self.parallel = args.parallel
        # 2D space parameter
        self.cellSize = 0.4 # m
        self.width = args.width  # in meters
        self.height = args.height  # in meters
        self.ncols = int(self.width / self.cellSize + 2 + 0.00000001)  # number of columns, add ghost cells
        self.nrows = int(self.height / self.cellSize + 2 + 0.00000001)  # number of rows, add ghost cells
        self.exit_cells = frozenset(((self.nrows // 2, self.ncols - 1), (self.nrows // 2 + 1, self.ncols - 1),
                                     (self.nrows - 1, self.ncols//2 + 1) , (self.nrows - 1, self.ncols//2),
                                     (0, self.ncols//2 + 1) , (1, self.ncols//2),
                                     (self.nrows//2 + 1, 0) , (self.nrows//2, 0)
        ))
        self.grid = list(it.product(range(1, self.nrows - 1), range(1, self.ncols - 1))) + list(self.exit_cells)
        # Simulation parameter
        self.box = args.box # where to distribute peds
        self.nruns = args.nruns
        self.MAX_STEPS = 1000
        self.steps = range(self.MAX_STEPS)
        self.vmax = 1.2
        self.dt = self.cellSize / self.vmax  # time step
        self.sim_time = 0
        self.run_time = 0
        self.clean_dirs = args.clean # clean up directories
        if self.box == [0, 10, 0, 10]:
            self.box = [1, self.nrows - 2, 1, self.ncols - 2]

        if self.drawP: self.setup_dir('peds', self.clean_dirs)
        if self.drawD or self.drawD_avg: self.setup_dir('dff', self.clean_dirs)
        self.init_simulation()
        # --------- init variables -------------

    def init_simulation(self):
        self.init_obstacles()
        self.init_walls()
        self.init_peds()
        self.init_sff()
        self.init_dff()
        # make some checks
        self.check_box()
        self.check_N_pedestrians()


    def check_box(self):
        """
        exit if box is not well defined
        """
        assert (self.box[0] < self.box[1]), "from_x bigger than to_x"
        assert (self.box[2] < self.box[3]), "from_y bigger than to_y"

    def check_N_pedestrians(self):
        """
        check if <N_pedestrian> is too big. if so change it to fit in <box>
        """
        # holding box, where to distribute pedestrians
        # ---------------------------------------------------
        _from_x = self.box[0]
        _to_x = self.box[1]
        _from_y = self.box[2]
        _to_y = self.box[3]
        # ---------------------------------------------------
        nx = _to_x - _from_x + 1
        ny = _to_y - _from_y + 1
        if self.npeds > nx * ny:
            logging.warning("N_pedestrians (%d) is too large (max. %d). Set to max." % (self.npeds, nx * ny))
            self.npeds = nx * ny

    def init_obstacles(self):
        self.obstacles = np.ones((self.nrows, self.ncols), int)  # obstacles/walls/boundaries

    @lru_cache(16*1024)
    def get_neighbors(self, cell):
        """
        von Neumann neighborhood or moore neighborhood
        """
        neighbors = []
        i, j = cell
        if i < self.nrows - 1 and self.walls[(i + 1, j)] >= 0:
            neighbors.append((i + 1, j))
        if i >= 1 and self.walls[(i - 1, j)] >= 0:
            neighbors.append((i - 1, j))
        if j < self.ncols - 1 and self.walls[(i, j + 1)] >= 0:
            neighbors.append((i, j + 1))
        if j >= 1 and self.walls[(i, j - 1)] >= 0:
            neighbors.append((i, j - 1))

        # moore
        if self.moore:
            if i >= 1 and j >= 1 and self.walls[(i-1, j - 1)] >= 0:
                neighbors.append((i-1, j - 1))
            if i < self.nrows - 1 and  j < self.ncols -1  and self.walls[(i+1, j+1)] >= 0:
                neighbors.append((i+1, j + 1))
            if i < self.nrows - 1 and  j >= 1  and self.walls[(i+1, j-1)] >= 0:
                neighbors.append((i+1, j - 1))
            if i >= 1 and  j < self.ncols -1  and self.walls[(i-1, j+1)] >= 0:
                neighbors.append((i-1, j + 1))


        # not shuffling singnificantly alters the simulation...
        random.shuffle(neighbors)
        return neighbors


    def init_walls(self):
        """
        define where are the walls. Consider the exits
        """
        walls = np.copy(self.obstacles)
        walls[0, :] = walls[-1, :] = walls[:, -1] = walls[:, 0] = -1
        for e in self.exit_cells:
            walls[e] = 1

        self.walls = walls

    def init_dff(self):
        """
        """
        self.dff = np.zeros((self.nrows, self.ncols))

    @lru_cache(1)
    def init_sff(self):
        # start with exit's cells
        SFF = np.empty((self.nrows, self.ncols))  # static floor field
        SFF[:] = np.sqrt(self.nrows ** 2 + self.ncols ** 2)

        cells_initialised = []
        for e in self.exit_cells:
            cells_initialised.append(e)
            SFF[e] = 0

        while cells_initialised:
            cell = cells_initialised.pop(0)
            neighbor_cells = self.get_neighbors(cell)
            for neighbor in neighbor_cells:
                if SFF[cell] + 1 < SFF[neighbor]:
                    SFF[neighbor] = SFF[cell] + 1
                    cells_initialised.append(neighbor)


        self.sff = SFF

    def init_peds(self):
        """
        distribute N pedestrians in box
        """
        from_x, to_x = self.box[:2]
        from_y, to_y = self.box[2:]
        nx = to_x - from_x + 1
        ny = to_y - from_y + 1
        PEDS = np.ones(self.npeds, int)  # pedestrians
        EMPTY_CELLS_in_BOX = np.zeros(nx * ny - self.npeds, int)  # the rest of cells in the box
        PEDS = np.hstack((PEDS, EMPTY_CELLS_in_BOX))  # put 0s and 1s together
        np.random.shuffle(PEDS)  # shuffle them
        PEDS = PEDS.reshape((nx, ny))  # reshape to a box
        EMPTY_CELLS = np.zeros((self.nrows, self.ncols), int)  # this is the simulation space
        EMPTY_CELLS[from_x:to_x + 1, from_y:to_y + 1] = PEDS  # put in the box
        logging.info("Init peds finished. Box: x: [%.2f, %.2f]. y: [%.2f, %.2f]",
                     from_x, to_x, from_y, to_y)

        self.peds = EMPTY_CELLS

    def update(self):
        """
        sequential update
        updates
        - peds
        - dff
        """

        tmp_peds = np.empty_like(self.peds)  # temporary cells
        np.copyto(tmp_peds, self.peds)

        dff_diff = np.zeros((self.nrows, self.ncols))
        if self.shuffle:  # sequential random update
            random.shuffle(self.grid)
        elif self.reverse:  # reversed sequential update
            self.grid.reverse()

        for (i, j) in self.grid:  # walk through all cells in geometry
            if self.peds[i, j] == 0:
                continue

            if (i, j) in self.exit_cells:
                tmp_peds[i, j] = 0
                dff_diff[i, j] += 1
                continue

            p = 0
            probs = {}
            cell = (i, j)
            for neighbor in self.get_neighbors(cell):  # get the sum of probabilities
                # original code:
                # probability = np.exp(-kappaS * sff[neighbor]) * np.exp(kappaD * dff[neighbor]) * \
                # (1 - tmp_peds[neighbor])
                # the absolute value of the exponents can get very large yielding 0 or
                # inifite probability.
                # to prevent this we multiply every probability with exp(kappaS * sff[cell) and
                # exp(-kappaD * dff[cell]).
                # since the probabilities are normalized this doesn't have any effect on the model

                probability = np.exp(self.kappaS * (self.sff[cell] - self.sff[neighbor])) * \
                              np.exp(self.kappaD * (self.dff[neighbor] - self.dff[cell])) * \
                              (1 - tmp_peds[neighbor])

                p += probability
                probs[neighbor] = probability

                if p == 0:  # pedestrian in cell can not move
                    continue

                r = np.random.rand() * p
                # print ("start update")
                for neighbor in self.get_neighbors(cell): #TODO: shuffle?
                    r -= probs[neighbor]
                    if r <= 0:  # move to neighbor cell
                        tmp_peds[neighbor] = 1
                        tmp_peds[i, j] = 0
                        dff_diff[i, j] += 1
                        break

        self.update_dff(dff_diff)
        self.peds = tmp_peds


    def update_dff(self, diff):
        self.dff += diff

        for i, j in it.chain(it.product(range(1, self.nrows - 1), range(1, self.ncols - 1)), self.exit_cells):
            for _ in range(int(self.dff[i, j])):
                if np.random.rand() < self.delta: # decay
                    self.dff[i, j] -= 1
                elif np.random.rand() < self.alpha: # diffusion
                    self.dff[i, j] -= 1
                    self.dff[random.choice(self.get_neighbors((i, j)))] += 1
            assert self.walls[i, j] > -1 or self.dff[i, j] == 0, (self.dff, i, j)


    def print_logs(self):
        """
        print some infos to the screen
        """
        print ("Simulation of %d pedestrians" % self.npeds)
        print ("Simulation space (%.2f x %.2f) m^2" % (self.width, self.height))
        print ("SFF:  %.2f | DFF: %.2f" % (self.kappaS, self.kappaD))
        print ("Mean Evacuation time: %.2f s, runs: %d" % (self.sim_time * self.dt / self.nruns, self.nruns))
        print ("Total Run time: %.2f s" % self.run_time)
        print ("Factor: x%.2f" % (self.dt * self.sim_time / self.run_time))


    def setup_dir(self, dir, clean):
        print("make ", dir)
        if os.path.exists(dir) and clean:
            os.system('rm -rf %s' % dir) # this is OS specific
        os.makedirs(dir, exist_ok=True)
