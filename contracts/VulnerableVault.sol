// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice Deliberately vulnerable. Mirrors the DAO withdrawal pattern.
contract VulnerableVault {
    mapping(address => uint256) public balances;
    uint256 public totalDeposits;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
        totalDeposits += msg.value;
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "nothing to withdraw");

        // Interaction before effects: control transfers to an unknown callee
        // which may re-enter withdraw() while balances[msg.sender] is stale.
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        balances[msg.sender] = 0;
        totalDeposits -= amount;

        /// @dev Solvency invariant: the vault never owes more than it holds.
        assert(totalDeposits <= address(this).balance);
    }
}
